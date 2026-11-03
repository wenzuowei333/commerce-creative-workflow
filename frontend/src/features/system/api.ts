import { useQuery } from "@tanstack/react-query";

import { apiRequest } from "../../api/client";

export type FeatureFlags = {
  live_provider: boolean;
  cos_media: boolean;
  image_revisions: boolean;
  hd_finalize: boolean;
  templates: boolean;
};

export type SystemInfo = {
  mode: "demo" | "live";
  persistent_queue: boolean;
  external_media: boolean;
  features?: Partial<FeatureFlags>;
};

const defaultFlags: FeatureFlags = {
  live_provider: false,
  cos_media: false,
  image_revisions: true,
  hd_finalize: false,
  templates: false,
};

export function useSystemInfo() {
  const query = useQuery({
    queryKey: ["system"],
    queryFn: () => apiRequest<SystemInfo>("/system"),
  });
  return {
    ...query,
    features: { ...defaultFlags, ...query.data?.features },
  };
}
