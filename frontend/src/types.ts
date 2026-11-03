export type Product = {
  id: string;
  name: string;
  sku: string;
  brand: string;
  status: string;
  profile: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type ProductAsset = {
  id: string;
  product_id: string;
  name: string;
  content_type: string;
  size_bytes: number;
  sha256: string;
  width: number | null;
  height: number | null;
  position: number;
  is_primary: boolean;
  angle: string;
  status: string;
  preview_url: string;
  thumbnail_url: string;
};

export type AnalysisAttribute = {
  key: string;
  value: unknown;
  confidence: number;
  inference_kind: string;
  source_asset_ids: string[];
  user_confirmed: boolean;
  high_risk: boolean;
};

export type Analysis = {
  id: string;
  version: number;
  status: string;
  result: {
    profile: Record<string, unknown>;
    attributes: AnalysisAttribute[];
    summary?: string;
  };
  confirmed_at: string | null;
};

export type PromptVariant = {
  index: number;
  module: string | null;
  prompt: string;
};

export type PromptDirection = {
  index: number;
  title: string;
  rationale: string;
  base_prompt: string;
  negative_prompt: string;
  variants: PromptVariant[];
};

export type PromptRecipe = {
  generation_type: "main" | "detail";
  image_count: number;
  quality: string;
  size: string;
  directions: PromptDirection[];
};

export type PromptPlan = {
  id: string;
  product_id?: string;
  generation_type: "main" | "detail";
  image_count: number;
  state: string;
  plan: PromptRecipe;
  active_version: number;
  confirmed_at: string | null;
};

export type GeneratedImage = {
  id: string;
  product_id: string;
  batch_id: string;
  format: "webp" | "png";
  width: number;
  height: number;
  quality: string;
  status: string;
  preview_url: string;
  created_at: string;
};

export type GenerationItem = {
  id: string;
  direction_id: string;
  index: number;
  module: string | null;
  kind: string;
  state: string;
  prompt: string;
  parent_image_id: string | null;
  attempts: number;
  error_code: string | null;
  error_message: string | null;
  image: GeneratedImage | null;
};

export type GenerationBatch = {
  plan_version: number;
  demo_scenario: string;
  id: string;
  product_id: string;
  prompt_plan_id: string;
  generation_type: "main" | "detail";
  image_count: number;
  state: string;
  progress: number;
  error_code: string | null;
  directions: Array<{ id: string; index: number; title: string; rationale: string }>;
  items: GenerationItem[];
  created_at: string;
  completed_at: string | null;
};

export type ProductWorkspace = {
  product: Product;
  assets: ProductAsset[];
  latest_analysis: Analysis | null;
  latest_prompt_plan: PromptPlan | null;
};

export type Template = {
  id: string;
  name: string;
  generation_type: "main" | "detail";
  recipe: PromptRecipe;
  is_protected: boolean;
  created_at: string;
  updated_at: string;
};

export type HistoryResponse = {
  items: Array<GenerationBatch & { product: Pick<Product, "id" | "name" | "sku"> }>;
  limit: number;
  offset: number;
  has_more: boolean;
};
