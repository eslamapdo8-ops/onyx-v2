/*
 * Simple UART Transmitter (8N1, no flow control)
 * Baud rate defined by CLK_DIV (clk_hz / baud)
 *
 * واجهة:
 *   clk, rst_n, start (نبضة), data (8-bit), tx (خرج), busy (عالٍ أثناء الإرسال)
 */

module uart_tx #(
    parameter CLK_DIV = 104   // 12MHz / 115200 ≈ 104
)(
    input  wire clk,
    input  wire rst_n,
    input  wire start,
    input  wire [7:0] data,
    output reg tx,
    output reg busy
);

    reg [3:0] bit_idx;
    reg [7:0] shift_reg;
    reg [7:0] tick_counter;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            tx <= 1;           // idle high
            busy <= 0;
            bit_idx <= 0;
            tick_counter <= 0;
            shift_reg <= 0;
        end else begin
            if (!busy) begin
                if (start) begin
                    busy <= 1;
                    tx <= 0;   // start bit
                    shift_reg <= data;
                    bit_idx <= 0;
                    tick_counter <= 0;
                end
            end else begin
                if (tick_counter >= CLK_DIV - 1) begin
                    tick_counter <= 0;
                    if (bit_idx < 8) begin
                        // Data bits (LSB first)
                        tx <= shift_reg[0];
                        shift_reg <= {1'b0, shift_reg[7:1]};
                        bit_idx <= bit_idx + 1;
                    end else begin
                        // Stop bit
                        tx <= 1;
                        busy <= 0;
                        bit_idx <= 0;
                    end
                end else begin
                    tick_counter <= tick_counter + 1;
                end
            end
        end
    end

endmodule
