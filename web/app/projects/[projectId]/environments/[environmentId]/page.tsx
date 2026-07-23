import { EnvironmentCanvas } from "./canvas";

/**
 * The canvas is the main region. This server component does nothing but unwrap
 * the route params — every byte of data comes from `lib/api.ts` on the client.
 */
export default async function EnvironmentPage({
  params,
}: {
  params: Promise<{ projectId: string; environmentId: string }>;
}) {
  const { environmentId } = await params;
  return <EnvironmentCanvas environmentId={environmentId} />;
}
