/*
 * Onyx V2 — Testbench v2 مع N_WINDOW=5 وأكثر تفصيلاً
 * =====================================================
 */
`timescale 1ns / 1ps

module tb_onyx_core_v2;

    reg clk, rst_n, start;
    reg signed [31:0] signal_value;
    wire done, decision;
    wire [15:0] total_fires;
    wire [31:0] debug_state;

    onyx_core #(.N_OSC(6), .N_WINDOW(3)) dut (
        .clk(clk), .rst_n(rst_n), .start(start),
        .signal_value(signal_value),
        .done(done), .decision(decision),
        .total_fires(total_fires), .debug_state(debug_state)
    );

    always #5 clk = ~clk;

    reg [31:0] sig_pos = 32'h2000_0000;  // +0.5 * TH
    reg [31:0] sig_neg = -32'h2000_0000; // -0.5 * TH

    integer i, correct;
    reg d;

    initial begin
        clk = 0; rst_n = 0; start = 0;
        #15 rst_n = 1;
        #10;

        $display("Onyx V2 — Debug: Testing single samples");
        $display("");

        // Test positive signal
        signal_value = sig_pos;
        start = 1; #10; start = 0;
        @(posedge done); #1;
        $display("POS signal (%0d): decision=%0d, fires=%0d, dbg=%h",
            sig_pos, decision, total_fires, debug_state);

        // Test negative signal
        signal_value = sig_neg;
        #20;
        start = 1; #10; start = 0;
        @(posedge done); #1;
        $display("NEG signal (%0d): decision=%0d, fires=%0d, dbg=%h",
            sig_neg, decision, total_fires, debug_state);

        // Full classification run
        $display("");
        $display("--- Full test: 25 POS + 25 NEG ---");
        correct = 0;
        for (i = 0; i < 25; i = i + 1) begin
            signal_value = sig_pos;
            start = 1; #10; start = 0;
            @(posedge done); #1;
            d = decision;
            if (d == 1) correct = correct + 1;
            else $display("  POS sample %0d FAILED (decision=%0d)", i, d);
            #10;
        end
        for (i = 0; i < 25; i = i + 1) begin
            signal_value = sig_neg;
            start = 1; #10; start = 0;
            @(posedge done); #1;
            d = decision;
            if (d == 0) correct = correct + 1;
            else $display("  NEG sample %0d FAILED (decision=%0d)", i, d);
            #10;
        end

        $display("");
        $display("Final: %0d/50 correct (%0.1f%%)",
            correct, correct * 2.0);
        $finish;
    end

    initial begin
        $dumpfile("tb_onyx_v2.vcd");
        $dumpvars(0, tb_onyx_core_v2);
    end

endmodule
