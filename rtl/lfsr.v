/*
 * Onyx V2 — LFSR Noise Generator
 * =================================
 * مولد ضوضاء رقمي شبه عشوائي (Linear Feedback Shift Register)
 * 32-bit Galois LFSR مع polynomial: x^32 + x^22 + x^2 + x^1 + 1
 *
 * المخرج noise: قيمة signed بين -2^31 و +2^31
 */

module lfsr #(
    parameter WIDTH = 32
)(
    input  wire                 clk,
    input  wire                 rst_n,
    input  wire                 enable,
    output reg  signed [WIDTH-1:0] noise
);

    reg [WIDTH-1:0] state;

    // Galois LFSR polynomial taps
    wire feedback = state[0];
    wire [WIDTH-1:0] next_state = {state[WIDTH-2:0], 1'b0};

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= 32'hACE1_42BD;  // seed غير صفري
            noise <= 0;
        end else if (enable) begin
            if (feedback) begin
                state <= next_state ^ 32'hB4BCD35C;  // polynomial mask
            end else begin
                state <= next_state;
            end
            // ضوضاء: نأخذ الـ 16-bit العليا ونطرح 2^15 لنجعلها signed
            noise <= {state[31:16], 16'h0000} - 32'h8000_0000;
        end
    end

endmodule
