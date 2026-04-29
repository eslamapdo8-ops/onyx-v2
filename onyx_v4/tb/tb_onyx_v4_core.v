/*
 * Onyx V4 — Testbench with real MNIST data (via .hex files)
 * ==========================================================
 * يقرأ 50 عينة من features_hex.txt، أوزان مدربة من weights_hex.txt،
 * ويقارن النتائج مع expected_labels.txt.
 *
 * N=16, N_CLASSES=2 (تصنيف ثنائي 0/1)
 */

`timescale 1ns / 1ps

module tb_onyx_v4;

    parameter N_OSC      = 16;
    parameter N_CLASSES  = 2;
    parameter ACC_WIDTH  = 32;
    parameter N_SAMPLES  = 50;

    reg clk, rst_n, start, load_weights;
    reg [7:0] weight_addr;
    reg signed [15:0] weight_data;
    reg signed [ACC_WIDTH-1:0] features_unpack [0:N_OSC-1];
    wire signed [ACC_WIDTH*N_OSC-1:0] features_packed;

    genvar fi;
    generate
        for (fi = 0; fi < N_OSC; fi = fi + 1) begin : pack_features
            assign features_packed[fi*ACC_WIDTH +: ACC_WIDTH] = features_unpack[fi];
        end
    endgenerate

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
        .features_packed(features_packed),
        .done(done), .class_id(class_id), .total_fires(total_fires)
    );

    always #5 clk = ~clk;

    // ── Memory arrays for .hex data ──
    reg signed [31:0] feature_mem [0:N_SAMPLES*N_OSC-1];
    reg signed [15:0] weight_mem_ref [0:N_CLASSES*N_OSC-1];
    reg [7:0] expected_labels [0:N_SAMPLES-1];

    integer i, j, s, correct;
    integer f_handle, w_handle, l_handle;

    initial begin
        clk = 0; rst_n = 0; start = 0; load_weights = 0;

        // ── Load features from .hex ──
        $display("Loading features_hex.txt...");
        $readmemh("features_hex.txt", feature_mem);
        $display("  %0d features loaded", N_SAMPLES * N_OSC);

        // ── Load weights from .hex ──
        $display("Loading weights_hex.txt...");
        $readmemh("weights_hex.txt", weight_mem_ref);
        $display("  %0d weights loaded", N_CLASSES * N_OSC);

        // ── Load expected labels ──
        $display("Loading expected_labels.txt...");
        l_handle = $fopen("expected_labels.txt", "r");
        if (l_handle == 0) begin
            $display("ERROR: cannot open expected_labels.txt");
            $finish;
        end
        for (s = 0; s < N_SAMPLES; s = s + 1)
            expected_labels[s] = $fgetc(l_handle) - 48; // ASCII '0'/'1' → integer
        $fclose(l_handle);
        $display("  %0d labels loaded", N_SAMPLES);

        #15 rst_n = 1;
        #10;

        // ── Load weights into core ──
        $display("");
        $display("Loading weights into core...");
        load_weights = 1;
        #5;
        for (i = 0; i < N_CLASSES * N_OSC; i = i + 1) begin
            weight_addr = i;
            weight_data = weight_mem_ref[i];
            #10;
        end
        load_weights = 0;
        #10;
        $display("  Weight[0]=%0d, Weight[16]=%0d", dut.weight_mem[0], dut.weight_mem[16]);

        // ── Test all 50 samples ──
        $display("");
        $display("── Testing %0d MNIST samples ──", N_SAMPLES);
        correct = 0;
        for (s = 0; s < N_SAMPLES; s = s + 1) begin
            // Load features for this sample
            for (j = 0; j < N_OSC; j = j + 1)
                features_unpack[j] = feature_mem[s * N_OSC + j];

            // Start classification
            #5 start = 1; #10 start = 0;
            @(posedge done); #1;

            if (class_id == expected_labels[s]) begin
                correct = correct + 1;
            end else begin
                $display("  MISMATCH[%0d]: expected=%0d, got=%0d, fires=%0d (fire_counts: %0d %0d %0d..., scores: %0d %0d)",
                    s, expected_labels[s], class_id, total_fires,
                    dut.osc_fire_counts[0*32+:32], dut.osc_fire_counts[1*32+:32], dut.osc_fire_counts[2*32+:32],
                    dut.scores[0], dut.scores[1]);
            end
            #10;
        end

        // ── Final report ──
        $display("");
        $display("═══════════════════════════════════");
        $display("  Final: %0d/%0d correct (%0.1f%%)", correct, N_SAMPLES, correct * 100.0 / N_SAMPLES);
        $display("  Expected: ~98% (matching Python prototype)");
        $display("═══════════════════════════════════");
        $finish;
    end

    initial begin
        $dumpfile("tb_onyx_v4.vcd");
        $dumpvars(0, tb_onyx_v4);
    end

endmodule
