// d3-force-3d ships no type declarations. We only use forceCollide, so a
// minimal ambient module is enough to satisfy the compiler.
declare module "d3-force-3d" {
  interface ForceCollide {
    (alpha?: number): void;
    radius(radius: number | ((node: any) => number)): ForceCollide;
    strength(strength: number): ForceCollide;
    iterations(iterations: number): ForceCollide;
  }
  export function forceCollide(radius?: number | ((node: any) => number)): ForceCollide;
}
