/*
 * Onyx V2 — NCO Oscillator مع LFSR مدمج
 * ========================================
 * كل مذبذب له LFSR الخاص به (seed مختلف).
 * 32-bit signed NCO + مقارنات عتبة + FDE
 */

module nco_oscillator #(
    parameter ACC_WIDTH = 32,
    parameter THRESHOLD = 32'h40000000,
    parameter OFFSET    = 32'h20000000,
    parameter LFSR_SEED = 32'hACE1_42BD
)(
    input  wire                 clk,
    input  wire                 rst_n,
    input  wire                 enable,
    input  wire                 reset_counts,   // إعادة تعيين الإطلاقات (لـ V4)
    input  wire signed [ACC_WIDTH-1:0] f_word,
    output reg                  fire_pos,
    output reg                  fire_neg,
    output reg  [ACC_WIDTH-1:0] fire_count,
    output reg                  firing_dir
);

    reg signed [ACC_WIDTH-1:0] acc;
    reg [ACC_WIDTH-1:0]        lfsr_state;

    // LFSR polynomial: x^32 + x^22 + x^2 + x^1 + 1
    wire feedback = lfsr_state[0];
    wire [ACC_WIDTH-1:0] next_lfsr = {lfsr_state[ACC_WIDTH-2:0], 1'b0};
    wire signed [ACC_WIDTH-1:0] noise =
                {lfsr_state[7:0], lfsr_state[15:8], lfsr_state[23:16], lfsr_state[31:24]} / 16;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            acc        <= 0;
            fire_pos   <= 0;
            fire_neg   <= 0;
            fire_count <= 0;
            firing_dir <= 0;
            lfsr_state <= LFSR_SEED;
        end else if (enable) begin
            // reset_counts + enable في نفس الدورة: fire_count يُصفّر أولاً
            // ثم يعمل NCO كالمعتاد
            if (reset_counts)
                fire_count <= 0;

            // LFSR step
            if (feedback)
                lfsr_state <= next_lfsr ^ 32'hB4BCD35C;
            else
                lfsr_state <= next_lfsr;

            // NCO accumulate: acc += f_word + noise
            acc <= acc + f_word + noise;

            // Threshold comparison
            if (acc > $signed(THRESHOLD)) begin
                fire_pos   <= 1;
                fire_neg   <= 0;
                firing_dir <= 1;
                acc        <= acc - $signed(OFFSET);
                fire_count <= fire_count + 1;
            end else if (acc < -$signed(THRESHOLD)) begin
                fire_neg   <= 1;
                fire_pos   <= 0;
                firing_dir <= 0;
                acc        <= acc + $signed(OFFSET);
                fire_count <= fire_count + 1;
            end else begin
                fire_pos <= 0;
                fire_neg <= 0;
            end
        end
    end

endmodule
