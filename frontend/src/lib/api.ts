const API_BASE_URL = (
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? ''
).replace(/\/+$/, '')

export interface DinoInfo {
  name: string;
  imageFile: string;
  maskFile: string;
  searchTerms: string[];
  usedRegions: number[];
}

export interface ColorEntry {
  ID: number;
  Name: string;
  Hex: string;
}

export interface RegionMapping {
  "Region ID": number;
  "Mask Color": string;
  RGB: [number, number, number];
}

export async function fetchDinoList(search?: string): Promise<DinoInfo[]> {
  const url = search
    ? `${API_BASE_URL}/api/dinos?search=${encodeURIComponent(search)}`
    : `${API_BASE_URL}/api/dinos`

  const response = await fetch(url)
  if (!response.ok) {
    throw new Error(`Failed to fetch dinos: ${response.status}`)
  }
  return response.json()
}

export async function fetchColors(): Promise<ColorEntry[]> {
  const response = await fetch(`${API_BASE_URL}/api/dinos/colors`)
  if (!response.ok) {
    throw new Error(`Failed to fetch colors: ${response.status}`)
  }
  return response.json()
}

export async function fetchRegions(): Promise<RegionMapping[]> {
  const response = await fetch(`${API_BASE_URL}/api/dinos/regions`)
  if (!response.ok) {
    throw new Error(`Failed to fetch regions: ${response.status}`)
  }
  const data = await response.json()
  return data.regions
}

export async function fetchColoredDino(
  dinoName: string,
  regionColors: Record<number, number>
): Promise<Blob> {
  const response = await fetch(`${API_BASE_URL}/api/dinos/render`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ dinoName, regionColors }),
  })

  if (!response.ok) {
    throw new Error(`Failed to render dino: ${response.status}`)
  }

  return response.blob()
}
