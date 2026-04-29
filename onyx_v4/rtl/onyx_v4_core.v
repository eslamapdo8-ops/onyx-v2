/*
 * Onyx V4 — NCO Array (Toplevel)
 * ================================
 * مصفوفة N من NCOs تعمل بالتوازي، مع Linear Readout.
 *
 * N = عدد المذبذبات (قابل للتوسيع)
 * N_WINDOW = 3 دورات ساعة
 * 
 * الدخل: درجات الميزات (features) بعد Random Projection (خارج الشريحة)
 * الخرج: class_id + valid
 *
 * آلية العمل:
 *   1. تُحمَّل الميزات feature[0..N-1] (32-bit signed لكل بُعد)
 *   2. NCOs تعمل لـ N_WINDOW دورات → توليد fingerprints (firing_dir لكل NCO)
 *   3. Linear Readout: score_c = sum_d(W[c][d] * fingerprint[d])
 *   4. Argmax → class_id
 *
 * الأوزان W (C × N) تُحمَّل مسبقاً عبر واجهة SPI/UART.
 *
 * الإصدار: v4.0.0-alpha
 */

module onyx_v4_core #(
    parameter N_OSC       = 16,           // عدد المذبذبات (قابل للتوسيع)
    parameter N_CLASSES   = 10,           // عدد فئات التصنيف
    parameter ACC_WIDTH   = 32,           // عرض accumulator
    parameter THRESHOLD   = 32'h40000000, // عتبة (±2^30)
    parameter OFFSET      = 32'h20000000, // إعادة الضبط
    parameter N_WINDOW    = 3,            // عدد دورات الساعة للتصنيف
    parameter W_WEIGHT_W  = 16            // عرض وزن القراءة الخطية (signed)
)(
    input  wire                         clk,
    input  wire                         rst_n,
    input  wire                         start,           // بدء تصنيف
    input  wire signed [ACC_WIDTH*N_OSC-1:0] features_packed, // N ميزة (متسلسلة)
    input  wire                         load_weights,    // تحميل أوزان القراءة
    input  wire [7:0]                   weight_addr,     // عنوان الوزن
    input  wire signed [W_WEIGHT_W-1:0] weight_data,     // بيانات الوزن
    output reg                          done,
    output reg  [7:0]                   class_id,        // الفئة المنتقاة (0..N_CLASSES-1)
    output reg  [15:0]                  total_fires      // إجمالي الإطلاقات
);

    // ========== Unpack features ==========
    wire signed [ACC_WIDTH-1:0] features [0:N_OSC-1];
    genvar fi;
    generate
        for (fi = 0; fi < N_OSC; fi = fi + 1) begin : feature_unpack
            assign features[fi] = features_packed[fi*ACC_WIDTH +: ACC_WIDTH];
        end
    endgenerate

    // ========== FSM ==========
    localparam IDLE      = 3'b000;
    localparam RUN       = 3'b001;
    localparam READOUT   = 3'b010;
    localparam DONE_ST   = 3'b011;
    localparam LOAD_W    = 3'b100;

    reg [2:0] state;
    reg [7:0] step_counter;

    // ========== NCO Array ==========
    wire [N_OSC-1:0]             osc_firing_dir;
    wire [N_OSC*ACC_WIDTH-1:0]   osc_fire_counts;
    wire                         reset_counts = (state == RUN && step_counter == 0);

    genvar i;
    generate
        for (i = 0; i < N_OSC; i = i + 1) begin : osc_bank
            localparam [31:0] OSC_TH = THRESHOLD +
                (THRESHOLD * ((i * 40) / (N_OSC * 100))) - (THRESHOLD / 5);
            localparam [31:0] OSC_SEED = 32'hBEEF_CAFE + (i * 32'h1000_0000);

            nco_oscillator #(
                .ACC_WIDTH(ACC_WIDTH),
                .THRESHOLD(OSC_TH),
                .OFFSET(OFFSET),
                .LFSR_SEED(OSC_SEED)
            ) osc (
                .clk(clk),
                .rst_n(rst_n),
                .enable((state == RUN)),
                .reset_counts(reset_counts),
                .f_word(features[i]),
                .fire_pos(),      // غير مستخدم — نكتفي بـ firing_dir
                .fire_neg(),
                .fire_count(osc_fire_counts[i*ACC_WIDTH +: ACC_WIDTH]),
                .firing_dir(osc_firing_dir[i])
            );
        end
    endgenerate

    // ========== Weight Memory (RAM) — N_CLASSES × N_OSC ==========
    reg signed [W_WEIGHT_W-1:0] weight_mem [0:N_CLASSES*N_OSC-1];
    integer w;

    // ========== Linear Readout ==========
    reg signed [31:0] scores [0:N_CLASSES-1];
    integer c, d;
    reg [7:0] best_class;
    reg signed [31:0] best_score;

    // ========== FSM ==========
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state        <= IDLE;
            done         <= 0;
            class_id     <= 0;
            total_fires  <= 0;
            step_counter <= 0;
        end else begin
            case (state)
                IDLE: begin
                    done <= 0;
                    if (load_weights) begin
                        state <= LOAD_W;
                    end else if (start) begin
                        state <= RUN;
                        step_counter <= 0;
                    end
                end

                RUN: begin
                    step_counter <= step_counter + 1;
                    if (step_counter >= N_WINDOW - 1) begin
                        state <= READOUT;
                    end
                end

                READOUT: begin
                    // حساب scores[c] = sum_d(weight_mem[c*N + d] × fingerprint[d])
                    // fingerprint[d] = +1 (firing_dir=1) أو -1 (firing_dir=0)
                    for (c = 0; c < N_CLASSES; c = c + 1) begin
                        scores[c] = 0;
                        for (d = 0; d < N_OSC; d = d + 1) begin
                            if (osc_firing_dir[d])
                                scores[c] = scores[c] + weight_mem[c * N_OSC + d];
                            else
                                scores[c] = scores[c] - weight_mem[c * N_OSC + d];
                        end
                    end
                    state <= DONE_ST;
                end

                DONE_ST: begin
                    // Argmax
                    best_class = 0;
                    best_score = scores[0];
                    for (c = 1; c < N_CLASSES; c = c + 1) begin
                        if (scores[c] > best_score) begin
                            best_score = scores[c];
                            best_class = c;
                        end
                    end
                    class_id <= best_class;
                    done <= 1;

                    if (!start && !load_weights) begin
                        state <= IDLE;
                    end
                end

                LOAD_W: begin
                    // تحميل وزن واحد في كل دورة
                    if (weight_addr < N_CLASSES * N_OSC) begin
                        weight_mem[weight_addr] <= weight_data;
                    end
                    if (!load_weights) begin
                        state <= IDLE;
                    end
                end
            endcase
        end
    end

    // ========== Total Fires ==========
    integer f;
    always @(*) begin
        total_fires = 0;
        for (f = 0; f < N_OSC; f = f + 1) begin
            total_fires = total_fires +
                osc_fire_counts[f*ACC_WIDTH +: ACC_WIDTH];
        end
    end

endmodule
