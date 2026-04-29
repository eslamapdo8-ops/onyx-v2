/*
 * Simple UART Receiver (8N1, no flow control)
 * Baud rate defined by CLK_DIV (clk_hz / baud)
 *
 * واجهة:
 *   clk, rst_n, rx (دخل), data (خرج 8-bit), valid (نبضة), busy (عالٍ أثناء الاستقبال)
 */

module uart_rx #(
    parameter CLK_DIV = 104   // 12MHz / 115200 ≈ 104
)(
    input  wire clk,
    input  wire rst_n,
    input  wire rx,
    output reg [7:0] data,
    output reg valid,
    output reg busy
);

    reg [3:0] bit_idx;
    reg [7:0] shift_reg;
    reg [7:0] tick_counter;
    reg [1:0] rx_sync;

    wire rx_clean;
    assign rx_clean = rx_sync[1];

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rx_sync <= 2'b11;
        end else begin
            rx_sync <= {rx_sync[0], rx};
        end
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            busy <= 0;
            valid <= 0;
            bit_idx <= 0;
            tick_counter <= 0;
            shift_reg <= 0;
            data <= 0;
        end else begin
            valid <= 0;

            if (!busy) begin
                // انتظار start bit (falling edge)
                if (!rx_clean) begin
                    busy <= 1;
                    tick_counter <= 0;
                    bit_idx <= 0;
                end
            end else begin
                // Sampling at mid-bit (CLK_DIV/2), then every CLK_DIV
                if (tick_counter == CLK_DIV/2 - 1 && bit_idx == 0) begin
                    // تأكيد start bit
                    if (rx_clean) begin
                        busy <= 0;  // false start
                    end else begin
                        tick_counter <= 0;
                        bit_idx <= 1;
                    end
                end else if (tick_counter >= CLK_DIV - 1) begin
                    tick_counter <= 0;
                    if (bit_idx <= 8) begin
                        // Data bits (LSB first)
                        shift_reg <= {rx_clean, shift_reg[7:1]};
                        bit_idx <= bit_idx + 1;
                    end else begin
                        // Stop bit
                        if (rx_clean) begin
                            data <= shift_reg;
                            valid <= 1;
                        end
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
