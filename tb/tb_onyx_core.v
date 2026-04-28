/*
 * Onyx V2 — Testbench للمحاكاة الزمنية
 * ========================================
 * يحاكي 50 عينة (25 موجبة + 25 سالبة).
 * يُحسب الدقة والمخرجات.
 *
 * التشغيل:
 *   iverilog -g2012 -o tb_onyx tb_onyx_core.v ../rtl/nco_oscillator.v ../rtl/lfsr.v ../rtl/voting_unit.v ../rtl/onyx_core.v
 *   vvp tb_onyx
 */

`timescale 1ns / 1ps

module tb_onyx_core;

    // ========== Parameters ==========
    parameter N_SAMPLES = 50;
    parameter CLK_PERIOD = 10;  // 100 MHz

    // ========== Signals ==========
    reg                 clk;
    reg                 rst_n;
    reg                 start;
    reg  signed [31:0]  signal_value;
    wire                done;
    wire                decision;
    wire [15:0]         total_fires;
    wire [31:0]         debug_state;

    // ========== DUT ==========
    onyx_core #(
        .N_OSC(6),
        .N_WINDOW(2)
    ) dut (
        .clk(clk),
        .rst_n(rst_n),
        .start(start),
        .signal_value(signal_value),
        .done(done),
        .decision(decision),
        .total_fires(total_fires),
        .debug_state(debug_state)
    );

    // ========== Clock ==========
    always #(CLK_PERIOD/2) clk = ~clk;

    // ========== Test ==========
    integer i, j, correct;
    reg [31:0] expected;
    reg [31:0] signals [0:49];
    reg [31:0] expecteds [0:49];

    initial begin
        // Read signals from file or generate
        // Using same signals as Python: 25 positive (+0.5*TH), 25 negative (-0.5*TH)
        for (i = 0; i < 25; i = i + 1) begin
            signals[i] = 32'h2000_0000;     // +0.5 * TH (~2^29)
            expecteds[i] = 1;
        end
        for (i = 25; i < 50; i = i + 1) begin
            signals[i] = -32'h2000_0000;    // -0.5 * TH (~ -2^29)
            expecteds[i] = 0;               // 0 = سالب
        end

        // Initialize
        clk = 0;
        rst_n = 0;
        start = 0;
        signal_value = 0;
        correct = 0;

        // Reset
        #20 rst_n = 1;
        #10;

        $display("==============================================================");
        $display("Onyx V2 — NCO Digital Verilog Simulation");
        $display("==============================================================");
        $display("Samples: %0d, N_WINDOW: %0d, Oscillators: 6", N_SAMPLES, dut.N_WINDOW);
        $display("");

        // Classify all samples
        for (i = 0; i < N_SAMPLES; i = i + 1) begin
            signal_value = signals[i];
            start = 1;
            #(CLK_PERIOD);
            start = 0;

            // Wait for done
            @(posedge done);
            #1;

            // Check result
            if (decision === expecteds[i]) begin
                correct = correct + 1;
                $display("Sample %0d: signal=%0d -> decision=%0d (expected=%0d) OK",
                    i, signals[i], decision, expecteds[i]);
            end else begin
                $display("Sample %0d: signal=%0d -> decision=%0d (expected=%0d) FAIL",
                    i, signals[i], decision, expecteds[i]);
            end

            #(CLK_PERIOD);
        end

        // Summary
        $display("");
        $display("==============================================================");
        $display("Results: %0d/%0d correct (%0.1f%%)",
            correct, N_SAMPLES, (correct * 100.0 / N_SAMPLES));
        $display("==============================================================");

        // Assert
        if (correct == N_SAMPLES) begin
            $display("VERIFICATION: ALL PASSED");
        end else begin
            $display("VERIFICATION: %0d FAILURES", N_SAMPLES - correct);
        end

        $finish;
    end

    // Watchdog
    initial begin
        #50000;  // 50 us max
        $display("TIMEOUT: Simulation exceeded 50 us");
        $finish;
    end

    // Dump waves (for GTKWave)
    initial begin
        $dumpfile("tb_onyx.vcd");
        $dumpvars(0, tb_onyx_core);
    end

endmodule
