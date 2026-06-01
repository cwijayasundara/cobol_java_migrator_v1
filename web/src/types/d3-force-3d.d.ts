// d3-force-3d ships no type declarations. We only use a few forces, so a
// minimal ambient module is enough to satisfy the compiler.
declare module "d3-force-3d" {
  interface ForceCollide {
    (alpha?: number): void;
    radius(radius: number | ((node: any) => number)): ForceCollide;
    strength(strength: number): ForceCollide;
    iterations(iterations: number): ForceCollide;
  }
  export function forceCollide(radius?: number | ((node: any) => number)): ForceCollide;

  // Positioning forces — an attractive pull toward a target x/y. Used to gather
  // disconnected nodes toward the origin so the graph stays compact.
  interface ForcePosition {
    (alpha?: number): void;
    strength(strength: number | ((node: any) => number)): ForcePosition;
    x(x: number | ((node: any) => number)): ForcePosition;
    y(y: number | ((node: any) => number)): ForcePosition;
  }
  export function forceX(x?: number | ((node: any) => number)): ForcePosition;
  export function forceY(y?: number | ((node: any) => number)): ForcePosition;
}
