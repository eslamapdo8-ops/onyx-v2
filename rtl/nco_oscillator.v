/*
 * Onyx V2 — NCO Oscillator
 * ==========================
 * 32-bit signed Numerically Controlled Oscillator
 * مع مقارنات عتبة موجبة/سالبة + Firing Direction Encoding
 *
 * المعاملات:
 *   ACC_WIDTH: 32 (عرض الـ accumulator)
 *   THRESHOLD: 32'h40000000 (2^30)
 *   OFFSET:    32'h20000000 (2^29 = TH/2)
 */

module nco_oscillator #(
    parameter ACC_WIDTH = 32,
    parameter THRESHOLD = 32'h40000000,
    parameter OFFSET    = 32'h20000000
)(
    input  wire                 clk,
    input  wire                 rst_n,
    input  wire                 enable,
    input  wire signed [ACC_WIDTH-1:0] f_word,    // كلمة التردد + الإشارة
    input  wire signed [ACC_WIDTH-1:0] noise,     // ضوضاء رقمية (من LFSR)
    output reg                  fire_pos,          // إطلاق موجب
    output reg                  fire_neg,          // إطلاق سالب
    output reg  [ACC_WIDTH-1:0] fire_count,        // عدد الإطلاقات (عرض كامل)
    output reg                  firing_dir         // اتجاه آخر إطلاق (1=موجب, 0=سالب)
);

    reg signed [ACC_WIDTH-1:0] acc;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            acc       <= 0;
            fire_pos  <= 0;
            fire_neg  <= 0;
            fire_count <= 0;
            firing_dir <= 0;
        end else if (enable) begin
            // تجميع: acc += f_word + noise
            acc <= acc + f_word + noise;
            
            // مقارنة العتبات
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
