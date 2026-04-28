/*
 * Onyx V2 — Core (Top Level)
 * ============================
 * خزان مذبذبات NCO + ضوضاء LFSR + تصويت FDE
 *
 * N_OSC = 6 مذبذبات
 * N_WINDOW = 2 دورات ساعة للتصنيف
 * N_SAMPLES = 50 تصنيف
 *
 * التحكم:
 *   start → يصنف عينة واحدة ← done = 1 مع decision
 *   يتم تغذية signal_value عبر واجهة 32-bit
 */

module onyx_core #(
    parameter N_OSC = 6,
    parameter ACC_WIDTH = 32,
    parameter THRESHOLD = 32'h40000000,
    parameter OFFSET    = 32'h20000000,
    parameter N_WINDOW  = 2
)(
    input  wire                 clk,
    input  wire                 rst_n,
    input  wire                 start,           // بدء تصنيف عينة
    input  wire signed [31:0]   signal_value,    // الإشارة الداخلة (signed)
    output reg                  done,             // انتهى التصنيف
    output reg                  decision,         // 1=موجب, 0=سالب
    output reg  [15:0]          total_fires,      // إجمالي الإطلاقات
    output reg  [31:0]          debug_state       // للحالة الداخلية (Debug)
);

    // ========== FSM States ==========
    localparam IDLE    = 2'b00;
    localparam RUN     = 2'b01;
    localparam VOTE    = 2'b10;
    localparam DONE_ST = 2'b11;

    reg [1:0] state;
    reg [7:0] step_counter;
    reg [7:0] sample_counter;

    // ========== NCO Oscillators x6 ==========
    wire [N_OSC-1:0]             osc_fire_pos;
    wire [N_OSC-1:0]             osc_fire_neg;
    wire [N_OSC-1:0]             osc_firing_dir;
    wire [N_OSC*ACC_WIDTH-1:0]   osc_fire_counts;

    // LFSR noise
    wire signed [31:0] noise;
    wire lfsr_enable = (state == RUN);

    lfsr #(.WIDTH(32)) noise_gen (
        .clk(clk),
        .rst_n(rst_n),
        .enable(lfsr_enable),
        .noise(noise)
    );

    // توليد المذبذبات
    genvar i;
    generate
        for (i = 0; i < N_OSC; i = i + 1) begin : osc_bank
            // عتبات مختلفة لكل مذبذب (0.8×TH إلى 1.2×TH)
            localparam [31:0] OSC_TH = THRESHOLD +
                (THRESHOLD * ((i * 40) / (N_OSC * 100))) - (THRESHOLD / 5);

            nco_oscillator #(
                .ACC_WIDTH(ACC_WIDTH),
                .THRESHOLD(OSC_TH),
                .OFFSET(OFFSET)
            ) osc (
                .clk(clk),
                .rst_n(rst_n),
                .enable((state == RUN)),
                .f_word(signal_value),
                .noise(noise),
                .fire_pos(osc_fire_pos[i]),
                .fire_neg(osc_fire_neg[i]),
                .fire_count(osc_fire_counts[i*ACC_WIDTH +: ACC_WIDTH]),
                .firing_dir(osc_firing_dir[i])
            );
        end
    endgenerate

    // ========== Voting Unit ==========
    wire vote_decision;
    wire vote_valid;

    voting_unit #(
        .N_INPUTS(N_OSC),
        .COUNT_WIDTH(ACC_WIDTH)
    ) voter (
        .firing_dir(osc_firing_dir),
        .fire_counts(osc_fire_counts),
        .decision(vote_decision),
        .valid(vote_valid)
    );

    // ========== FSM ==========
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state        <= IDLE;
            done         <= 0;
            decision     <= 0;
            total_fires  <= 0;
            step_counter <= 0;
            sample_counter <= 0;
            debug_state  <= 0;
        end else begin
            case (state)
                IDLE: begin
                    done <= 0;
                    if (start) begin
                        state <= RUN;
                        step_counter <= 0;
                    end
                    debug_state <= 32'h0000_0001;
                end

                RUN: begin
                    step_counter <= step_counter + 1;
                    debug_state <= {24'h0000_01, step_counter};

                    if (step_counter >= N_WINDOW - 1) begin
                        state <= VOTE;
                    end
                end

                VOTE: begin
                    // Collect total fires
                    total_fires <=
                        osc_fire_counts[0*ACC_WIDTH +: ACC_WIDTH] +
                        osc_fire_counts[1*ACC_WIDTH +: ACC_WIDTH] +
                        osc_fire_counts[2*ACC_WIDTH +: ACC_WIDTH] +
                        osc_fire_counts[3*ACC_WIDTH +: ACC_WIDTH] +
                        osc_fire_counts[4*ACC_WIDTH +: ACC_WIDTH] +
                        osc_fire_counts[5*ACC_WIDTH +: ACC_WIDTH];
                    state <= DONE_ST;
                    debug_state <= 32'h0000_0003;
                end

                DONE_ST: begin
                    decision <= vote_decision;
                    done <= 1;
                    debug_state <= {16'h0000, 8'hFF, vote_decision, 7'b0, 1'b1};
                    if (!start) begin
                        state <= IDLE;
                    end
                end
            endcase
        end
    end

endmodule
