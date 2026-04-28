/*
 * Onyx V2 — Voting Unit (FDE)
 * =============================
 * Firing Direction Encoding voting.
 * N_INPUTS مذبذبات، كل واحد يعطي firing_dir.
 * القرار: majority vote — pos vs neg.
 *
 * كسر التعادل: مجموع fire_counts.
 */

module voting_unit #(
    parameter N_INPUTS = 6,
    parameter COUNT_WIDTH = 32
)(
    input  wire [N_INPUTS-1:0]             firing_dir,   // 1=pos, 0=neg
    input  wire [N_INPUTS*COUNT_WIDTH-1:0] fire_counts,  // متسلسلة
    output reg                             decision,     // 1=موجب, 0=سالب
    output reg                             valid         // قرار صحيح
);

    integer i;
    reg [31:0] pos_votes;
    reg [31:0] neg_votes;
    reg [COUNT_WIDTH-1:0] pos_fires;
    reg [COUNT_WIDTH-1:0] neg_fires;

    always @(*) begin
        pos_votes = 0;
        neg_votes = 0;
        pos_fires = 0;
        neg_fires = 0;

        for (i = 0; i < N_INPUTS; i = i + 1) begin
            if (firing_dir[i]) begin
                pos_votes = pos_votes + 1;
                pos_fires = pos_fires + fire_counts[i*COUNT_WIDTH +: COUNT_WIDTH];
            end else begin
                neg_votes = neg_votes + 1;
                neg_fires = neg_fires + fire_counts[i*COUNT_WIDTH +: COUNT_WIDTH];
            end
        end

        if (pos_votes > neg_votes) begin
            decision = 1;
            valid = 1;
        end else if (neg_votes > pos_votes) begin
            decision = 0;
            valid = 1;
        end else begin
            // Tiebreak: مجموع الإطلاقات
            decision = (pos_fires >= neg_fires) ? 1 : 0;
            valid = 1;
        end
    end

endmodule
