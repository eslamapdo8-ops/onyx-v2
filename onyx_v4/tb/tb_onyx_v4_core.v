/*
 * Onyx V4 — Testbench for NCO Array (N=16, binary/3-class)
 * ==========================================================
 * يختبر التصنيف لـ 4 إشارات ثنائية (+/- 0.5) بعد تحميل أوزان بسيطة.
 * 
 * N=16, N_CLASSES=2 (تصنيف ثنائي)
 * الأوزان: class0 = [+1, -1, +1, -1, ...], class1 = [-1, +1, -1, +1, ...]
 */

`timescale 1ns / 1ps

module tb_onyx_v4;

    parameter N_OSC = 16;
    parameter N_CLASSES = 2;
    parameter ACC_WIDTH = 32;

    reg clk, rst_n, start, load_weights;
    reg [7:0] weight_addr;
    reg signed [15:0] weight_data;
    reg signed [ACC_WIDTH-1:0] features [0:N_OSC-1];

    wire done;
    wire [7:0] class_id;
    wire [15:0] total_fires;

    onyx_v4_core #(
        .N_OSC(N_OSC),
        .N_CLASSES(N_CLASSES)
    ) dut (
        .clk(clk), .rst_n(rst_n),
        .start(start), .load_weights(load_weights),
        .weight_addr(weight_addr), .weight_data(weight_data),
        .features(features),
        .done(done), .class_id(class_id), .total_fires(total_fires)
    );

    always #5 clk = ~clk;

    integer i, j, correct;
    reg [31:0] sig_pos = 32'h2000_0000;   // +0.5
    reg [31:0] sig_neg = -32'h2000_0000;  // -0.5

    initial begin
        clk = 0; rst_n = 0; start = 0; load_weights = 0;
        #15 rst_n = 1;
        #10;

        // ========== Load Weights ==========
        $display("Loading weights...");
        load_weights = 1;
        // Class 0: alternating +1/-1
        for (i = 0; i < N_OSC; i = i + 1) begin
            weight_addr = i;  // class 0, feature i
            weight_data = (i % 2 == 0) ? 16'd1 : -16'd1;
            #10;
        end
        // Class 1: alternating -1/+1
        for (i = 0; i < N_OSC; i = i + 1) begin
            weight_addr = N_OSC + i;  // class 1, feature i
            weight_data = (i % 2 == 0) ? -16'd1 : 16'd1;
            #10;
        end
        load_weights = 0;
        #10;

        // ========== Test Positive Signal ==========
        $display("");
        $display("--- Testing POSITIVE signal ---");
        for (i = 0; i < N_OSC; i = i + 1) begin
            features[i] = sig_pos;
        end
        start = 1; #10; start = 0;
        @(posedge done); #1;
        $display("  POS: class_id=%0d, fires=%0d (expected=0)", class_id, total_fires);

        // ========== Test Negative Signal ==========
        $display("");
        $display("--- Testing NEGATIVE signal ---");
        for (i = 0; i < N_OSC; i = i + 1) begin
            features[i] = sig_neg;
        end
        #20;
        start = 1; #10; start = 0;
        @(posedge done); #1;
        $display("  NEG: class_id=%0d, fires=%0d (expected=1)", class_id, total_fires);

        // ========== Full Test: 25 POS + 25 NEG ==========
        $display("");
        $display("--- Full test: 25 POS + 25 NEG ---");
        correct = 0;

        for (i = 0; i < 25; i = i + 1) begin
            for (j = 0; j < N_OSC; j = j + 1)
                features[j] = sig_pos;
            #5 start = 1; #10 start = 0;
            @(posedge done); #1;
            if (class_id == 0) correct = correct + 1;
            else $display("  POS sample %0d FAILED (class=%0d)", i, class_id);
            #10;
        end

        for (i = 0; i < 25; i = i + 1) begin
            for (j = 0; j < N_OSC; j = j + 1)
                features[j] = sig_neg;
            #5 start = 1; #10 start = 0;
            @(posedge done); #1;
            if (class_id == 1) correct = correct + 1;
            else $display("  NEG sample %0d FAILED (class=%0d)", i, class_id);
            #10;
        end

        $display("");
        $display("Final: %0d/50 correct (%0.1f%%)", correct, correct * 2.0);
        $finish;
    end

    initial begin
        $dumpfile("tb_onyx_v4.vcd");
        $dumpvars(0, tb_onyx_v4);
    end

endmodule
