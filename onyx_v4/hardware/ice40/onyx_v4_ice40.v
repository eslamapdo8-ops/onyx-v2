/*
 * Onyx V4 — iCE40 UP5K Top-level (iCEBreaker board)
 * ====================================================
 * N=16 NCO Array + Linear Readout + UART (115200 8N1)
 *
 * يستقبل الأوزان والميزات عبر UART، ويعيد class_id + scores.
 *
 * البروتوكول (انظر ICE40_BRINGUP.md للتفاصيل):
 *   تحميل وزن: 0xFE addr_hi addr_lo data_hi data_lo
 *   تصنيف:     0xFD feat_0..feat_15 (كل 32-bit little-endian)
 *   نتيجة:     0xFC class_id fires_lo fires_hi score0_lo..score0_hi score1_lo..score1_hi
 *
 * الساعة: 12 MHz (on-board oscillator)
 * Baud: 115200 → كل بت ≈ 104.17 µs ≈ 1250 cycle @ 12 MHz
 */

module onyx_v4_ice40 (
    input  wire clk_12mhz,      // 12 MHz oscillator
    input  wire rst_n,           // زر إعادة تعيين (active low)
    input  wire uart_rx,        // UART receive
    output wire uart_tx,        // UART transmit
    output wire [7:0] led,      // 8× LEDs (debug)
    output wire led_green,      // مؤشر التشغيل
    output wire led_red         // مؤشر الخطأ
);

    // ========== Parameters ==========
    localparam CLK_HZ   = 12_000_000;
    localparam BAUD     = 115200;
    localparam BAUD_TICKS = CLK_HZ / BAUD;  // ≈ 104

    localparam N_OSC     = 16;
    localparam N_CLASSES = 2;
    localparam ACC_WIDTH = 32;
    localparam W_WEIGHT_W = 16;
    localparam N_WINDOW  = 20;

    // ========== Clock Divider for UART ==========
    reg [7:0] baud_counter;
    reg baud_tick;
    always @(posedge clk_12mhz or negedge rst_n) begin
        if (!rst_n) begin
            baud_counter <= 0;
            baud_tick <= 0;
        end else begin
            if (baud_counter >= BAUD_TICKS - 1) begin
                baud_counter <= 0;
                baud_tick <= 1;
            end else begin
                baud_counter <= baud_counter + 1;
                baud_tick <= 0;
            end
        end
    end

    // ========== UART Receiver ==========
    reg [7:0] rx_data;
    reg rx_valid;
    wire rx_busy;

    uart_rx #(.CLK_DIV(BAUD_TICKS))
    u_rx (
        .clk(clk_12mhz),
        .rst_n(rst_n),
        .rx(uart_rx),
        .data(rx_data),
        .valid(rx_valid),
        .busy(rx_busy)
    );

    // ========== UART Transmitter ==========
    reg [7:0] tx_data;
    reg tx_start;
    wire tx_busy;

    uart_tx #(.CLK_DIV(BAUD_TICKS))
    u_tx (
        .clk(clk_12mhz),
        .rst_n(rst_n),
        .start(tx_start),
        .data(tx_data),
        .tx(uart_tx),
        .busy(tx_busy)
    );

    // ========== Onyx V4 Core ==========
    wire signed [ACC_WIDTH*N_OSC-1:0] features_packed;
    wire signed [ACC_WIDTH-1:0] features_unpack [0:N_OSC-1];
    genvar fi;
    generate
        for (fi = 0; fi < N_OSC; fi = fi + 1) begin : pack_features
            assign features_packed[fi*ACC_WIDTH +: ACC_WIDTH] = features_unpack[fi];
        end
    endgenerate

    wire core_done;
    wire [7:0] core_class_id;
    wire [15:0] core_total_fires;
    reg core_start;
    reg core_load_weights;
    reg [7:0] core_weight_addr;
    reg signed [W_WEIGHT_W-1:0] core_weight_data;

    onyx_v4_core #(
        .N_OSC(N_OSC),
        .N_CLASSES(N_CLASSES),
        .N_WINDOW(N_WINDOW)
    ) core (
        .clk(clk_12mhz),
        .rst_n(rst_n),
        .start(core_start),
        .load_weights(core_load_weights),
        .weight_addr(core_weight_addr),
        .weight_data(core_weight_data),
        .features_packed(features_packed),
        .done(core_done),
        .class_id(core_class_id),
        .total_fires(core_total_fires)
    );

    // ========== FSM for UART Protocol ==========
    localparam IDLE       = 4'd0;
    localparam GET_CMD    = 4'd1;
    localparam LOAD_ADDR  = 4'd2;
    localparam LOAD_DATA  = 4'd3;
    localparam SEND_ACK   = 4'd4;
    localparam GET_FEAT   = 4'd5;
    localparam WAIT_DONE  = 4'd6;
    localparam SEND_RES   = 4'd7;

    reg [3:0] state;
    reg [3:0] feat_byte_cnt;   // 0..63 (16×32-bit = 64 bytes)
    reg [3:0] res_byte_cnt;    // 0..11
    reg [31:0] feat_buf [0:15]; // المخزن المؤقت للميزات
    reg [7:0] ack_addr;
    reg [15:0] ack_data;
    reg [7:0] result_buf [0:11];

    always @(posedge clk_12mhz or negedge rst_n) begin
        if (!rst_n) begin
            state <= IDLE;
            core_start <= 0;
            core_load_weights <= 0;
            tx_start <= 0;
            feat_byte_cnt <= 0;
            res_byte_cnt <= 0;
        end else begin
            case (state)
                IDLE: begin
                    if (rx_valid) begin
                        if (rx_data == 8'hFE) begin      // Load weight
                            state <= LOAD_ADDR;
                        end else if (rx_data == 8'hFD) begin  // Classify
                            state <= GET_FEAT;
                            feat_byte_cnt <= 0;
                        end
                    end
                end

                // ── Weight Loading ──
                LOAD_ADDR: begin
                    if (rx_valid) begin
                        ack_addr <= rx_data;
                        state <= LOAD_DATA;
                    end
                end

                LOAD_DATA: begin
                    if (rx_valid) begin
                        ack_data[15:8] <= rx_data;
                        state <= LOAD_DATA2;
                    end
                end

                LOAD_DATA2: begin
                    if (rx_valid) begin
                        ack_data[7:0] <= rx_data;
                        // Load into core
                        core_weight_addr <= ack_addr;
                        core_weight_data <= $signed(ack_data);
                        core_load_weights <= 1;
                        state <= SEND_ACK;
                    end
                end

                SEND_ACK: begin
                    core_load_weights <= 0;
                    if (!tx_busy) begin
                        tx_data <= 8'hFF;  // ACK
                        tx_start <= 1;
                        state <= SEND_ACK2;
                    end
                end

                SEND_ACK2: begin
                    tx_start <= 0;
                    if (!tx_busy) begin
                        tx_data <= ack_addr;
                        tx_start <= 1;
                        state <= SEND_ACK3;
                    end
                end

                SEND_ACK3: begin
                    tx_start <= 0;
                    if (!tx_busy) begin
                        tx_data <= ack_data[15:8];
                        tx_start <= 1;
                        state <= SEND_ACK4;
                    end
                end

                SEND_ACK4: begin
                    tx_start <= 0;
                    if (!tx_busy) begin
                        tx_data <= ack_data[7:0];
                        tx_start <= 1;
                        state <= IDLE;
                    end
                end

                // ── Classification ──
                GET_FEAT: begin
                    if (rx_valid) begin
                        // Collect 64 bytes → 16×32-bit little-endian
                        case (feat_byte_cnt[1:0])
                            2'd0: feat_buf[feat_byte_cnt[5:2]] <= {rx_data, 24'h0};
                            2'd1: feat_buf[feat_byte_cnt[5:2]] <= feat_buf[feat_byte_cnt[5:2]] | ({8'h0, rx_data, 16'h0});
                            2'd2: feat_buf[feat_byte_cnt[5:2]] <= feat_buf[feat_byte_cnt[5:2]] | ({16'h0, rx_data, 8'h0});
                            2'd3: feat_buf[feat_byte_cnt[5:2]] <= feat_buf[feat_byte_cnt[5:2]] | ({24'h0, rx_data});
                        endcase
                        feat_byte_cnt <= feat_byte_cnt + 1;
                        if (feat_byte_cnt >= 63) begin  // 64 bytes received
                            // Transfer features to core
                            for (integer ff = 0; ff < N_OSC; ff = ff + 1)
                                features_unpack[ff] <= $signed(feat_buf[ff]);
                            core_start <= 1;
                            state <= WAIT_DONE;
                        end
                    end
                end

                WAIT_DONE: begin
                    core_start <= 0;
                    if (core_done) begin
                        // Build result buffer
                        result_buf[0]  <= 8'hFC;
                        result_buf[1]  <= core_class_id;
                        result_buf[2]  <= core_total_fires[7:0];
                        result_buf[3]  <= core_total_fires[15:8];
                        result_buf[4]  <= 8'h00; // scores not exposed as wire yet
                        result_buf[5]  <= 8'h00;
                        result_buf[6]  <= 8'h00;
                        result_buf[7]  <= 8'h00;
                        result_buf[8]  <= 8'h00;
                        result_buf[9]  <= 8'h00;
                        result_buf[10] <= 8'h00;
                        result_buf[11] <= 8'h00;
                        res_byte_cnt <= 0;
                        state <= SEND_RES;
                    end
                end

                SEND_RES: begin
                    if (!tx_busy) begin
                        tx_data <= result_buf[res_byte_cnt];
                        tx_start <= 1;
                        if (res_byte_cnt >= 11) begin
                            state <= IDLE;
                        end else begin
                            res_byte_cnt <= res_byte_cnt + 1;
                            state <= SEND_RES_NEXT;
                        end
                    end
                end

                SEND_RES_NEXT: begin
                    tx_start <= 0;
                    state <= SEND_RES;
                end

                default: state <= IDLE;
            endcase
        end
    end

    // ========== Debug LEDs ==========
    reg [23:0] led_counter;
    always @(posedge clk_12mhz or negedge rst_n) begin
        if (!rst_n) begin
            led_counter <= 0;
        end else begin
            led_counter <= led_counter + 1;
        end
    end

    assign led = {
        core_done,                  // bit 7: done flag
        ~tx_busy,                   // bit 6: TX ready
        rx_valid,                   // bit 5: RX received
        (state == WAIT_DONE),       // bit 4: classifying
        (state == IDLE),            // bit 3: idle
        led_counter[23],            // bit 2: heartbeat
        led_counter[22],            // bit 1: heartbeat
        led_counter[21]             // bit 0: heartbeat
    };

    assign led_green = 1'b1;        // power indicator
    assign led_red = (state == IDLE && rx_valid && rx_data != 8'hFE && rx_data != 8'hFD);

endmodule
