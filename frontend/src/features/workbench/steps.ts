import type { ProductWorkspace } from "../../types";

export function deriveWorkspaceStep(workspace: ProductWorkspace | undefined): number {
  if (!workspace || workspace.assets.length === 0) return 1;
  const analysis = workspace.latest_analysis;
  if (!analysis || analysis.status !== "confirmed") return analysis ? 2 : 1;
  const prompt = workspace.latest_prompt_plan;
  if (!prompt || prompt.state !== "confirmed") return 3;
  return 4;
}
