import type { ReactNode } from "react";

// The 5-region cockpit frame. Journey Rail + Stage Header + Agent Console +
// Evidence Drawer are rendered by the stage page (it knows the active stage);
// this layout just provides the stable outer chrome + scroll containers.
export default async function WorkspaceLayout({
  children,
}: {
  children: ReactNode;
  params: Promise<{ id: string }>;
}) {
  return <div className="flex h-screen overflow-hidden">{children}</div>;
}
