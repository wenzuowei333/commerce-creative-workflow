import { apiRequest, sha256, uploadToSignedUrl } from "../../api/client";
import type { Product, ProductWorkspace } from "../../types";

type UploadSlot = {
  asset_id: string;
  upload_url: string;
  headers: Record<string, string>;
};

export function listProducts(): Promise<Product[]> {
  return apiRequest<Product[]>("/products");
}

export function getWorkspace(productId: string): Promise<ProductWorkspace> {
  return apiRequest<ProductWorkspace>(`/products/${productId}`);
}

export async function uploadProductFiles(productId: string, files: File[]): Promise<void> {
  const specs = await Promise.all(
    files.map(async (file) => ({
      name: file.name,
      content_type: file.type,
      size_bytes: file.size,
      sha256: await sha256(file),
    })),
  );
  const slots = await apiRequest<UploadSlot[]>("/assets/upload-requests", {
    method: "POST",
    idempotent: true,
    body: { product_id: productId, files: specs },
  });
  try {
    await Promise.all(
      slots.map(async (slot, index) => {
        await uploadToSignedUrl(slot.upload_url, files[index], slot.headers);
        await apiRequest(`/assets/${slot.asset_id}/confirm`, {
          method: "POST",
          idempotent: true,
        });
      }),
    );
  } catch (error) {
    await Promise.allSettled(
      slots.map((slot) => apiRequest(`/assets/${slot.asset_id}`, { method: "DELETE" })),
    );
    throw error;
  }
}
