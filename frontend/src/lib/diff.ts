export type DiffPart = { text: string; type: "same" | "add" | "del" };

/** Word-level LCS diff used to show what a suggested rewrite changed. */
export function wordDiff(a: string, b: string): DiffPart[] {
  const A = a.split(/(\s+)/).filter(Boolean);
  const B = b.split(/(\s+)/).filter(Boolean);
  const m = A.length;
  const n = B.length;
  const dp: number[][] = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));
  for (let i = m - 1; i >= 0; i--) {
    for (let j = n - 1; j >= 0; j--) {
      dp[i][j] = A[i].toLowerCase() === B[j].toLowerCase() ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const out: DiffPart[] = [];
  const push = (text: string, type: DiffPart["type"]) => {
    const last = out[out.length - 1];
    if (last && last.type === type) last.text += text;
    else out.push({ text, type });
  };
  let i = 0;
  let j = 0;
  while (i < m && j < n) {
    if (A[i].toLowerCase() === B[j].toLowerCase()) { push(B[j], "same"); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) { push(A[i], "del"); i++; }
    else { push(B[j], "add"); j++; }
  }
  while (i < m) push(A[i++], "del");
  while (j < n) push(B[j++], "add");
  return out;
}
