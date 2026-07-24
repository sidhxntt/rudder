"use client";

/**
 * TanStack Query bindings over `lib/api.ts`. Components call these; they never
 * call the API module directly and never call `fetch` at all (PRD → Stack:
 * "State — TanStack Query").
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import * as api from "./api";
import type { Deployment, ServiceUpdate } from "./types";

export const keys = {
  githubImportStatus: ["github-import-status"] as const,
  githubInstallations: ["github-installations"] as const,
  githubRepositories: (installationId: number) => ["github-repositories", installationId] as const,
  githubBranches: (installationId: number, repository: string) =>
    ["github-branches", installationId, repository] as const,
  githubPreview: (installationId: number, repository: string, branch: string) =>
    ["github-preview", installationId, repository, branch] as const,
  githubImport: (importId: string) => ["github-import", importId] as const,
  projects: ["projects"] as const,
  environments: (projectId: string) => ["environments", projectId] as const,
  services: (environmentId: string) => ["services", environmentId] as const,
  domains: (environmentId: string) => ["domains", environmentId] as const,
  deployments: (serviceId: string) => ["deployments", serviceId] as const,
  instances: (serviceId: string) => ["instances", serviceId] as const,
  variables: (serviceId: string) => ["variables", serviceId] as const,
};

export function useGitHubImportStatus() {
  return useQuery({ queryKey: keys.githubImportStatus, queryFn: api.getGitHubImportStatus });
}

export function useGitHubInstallations(enabled: boolean) {
  return useQuery({
    queryKey: keys.githubInstallations,
    queryFn: api.listGitHubInstallations,
    enabled,
  });
}

export function useGitHubRepositories(installationId: number | null) {
  return useQuery({
    queryKey: keys.githubRepositories(installationId ?? 0),
    queryFn: () => api.listGitHubRepositories(installationId ?? 0),
    enabled: installationId !== null,
  });
}

export function useGitHubBranches(installationId: number | null, repository: string | null) {
  return useQuery({
    queryKey: keys.githubBranches(installationId ?? 0, repository ?? ""),
    queryFn: () => api.listGitHubBranches(installationId ?? 0, repository ?? ""),
    enabled: installationId !== null && repository !== null,
  });
}

export function useGitHubImportPreview(
  installationId: number | null,
  repository: string | null,
  branch: string | null,
) {
  return useQuery({
    queryKey: keys.githubPreview(installationId ?? 0, repository ?? "", branch ?? ""),
    queryFn: () =>
      api.previewGitHubImport({
        installationId: installationId ?? 0,
        repository: repository ?? "",
        branch: branch ?? "",
      }),
    enabled: installationId !== null && repository !== null && branch !== null,
  });
}

export function useConfirmGitHubImport() {
  return useMutation({ mutationFn: api.confirmGitHubImport });
}

export function useGitHubImport(importId: string | null) {
  return useQuery({
    queryKey: keys.githubImport(importId ?? ""),
    queryFn: () => api.getGitHubImport(importId ?? ""),
    enabled: importId !== null,
    refetchInterval: LIVE_POLL_MS,
  });
}

/** Slow enough not to hammer the control plane, fast enough to watch a deploy. */
const LIVE_POLL_MS = 2_000;

export function useProjects() {
  return useQuery({ queryKey: keys.projects, queryFn: api.listProjects });
}

export function useEnvironments(projectId: string | undefined) {
  return useQuery({
    queryKey: keys.environments(projectId ?? ""),
    queryFn: () => api.listEnvironments(projectId ?? ""),
    enabled: Boolean(projectId),
  });
}

export function useServices(environmentId: string | undefined) {
  return useQuery({
    queryKey: keys.services(environmentId ?? ""),
    queryFn: () => api.listServices(environmentId ?? ""),
    enabled: Boolean(environmentId),
  });
}

export function useDomains(environmentId: string | undefined) {
  return useQuery({
    queryKey: keys.domains(environmentId ?? ""),
    queryFn: () => api.listDomains(environmentId ?? ""),
    enabled: Boolean(environmentId),
  });
}

export function useDeployments(serviceId: string | undefined) {
  return useQuery({
    queryKey: keys.deployments(serviceId ?? ""),
    queryFn: () => api.listDeployments(serviceId ?? ""),
    enabled: Boolean(serviceId),
    refetchInterval: LIVE_POLL_MS,
  });
}

export function useInstances(serviceId: string | undefined) {
  return useQuery({
    queryKey: keys.instances(serviceId ?? ""),
    queryFn: () => api.listInstances(serviceId ?? ""),
    enabled: Boolean(serviceId),
    refetchInterval: LIVE_POLL_MS,
  });
}

export function useVariables(serviceId: string | undefined) {
  return useQuery({
    queryKey: keys.variables(serviceId ?? ""),
    queryFn: () => api.listVariables(serviceId ?? ""),
    enabled: Boolean(serviceId),
  });
}

// Build logs are deliberately absent from this file. `GET
// /deployments/{id}/build-log` is an SSE stream, not a document with a URL you
// can refetch, so there is nothing for a query cache to hold. `build-logs.tsx`
// subscribes to `api.streamBuildLog` directly. Build logs only — runtime logs
// are Phase 5 (D4) and no view for them exists anywhere in this tree.

/** Canvas drag → PATCH /services/{id}. UI metadata only (D6). */
export function useUpdateServicePosition(environmentId: string | undefined) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (args: { serviceId: string; patch: ServiceUpdate }) =>
      api.updateService(args.serviceId, args.patch),
    onSuccess: () => {
      if (environmentId) {
        void client.invalidateQueries({ queryKey: keys.services(environmentId) });
      }
    },
  });
}

export function useDeploy(serviceId: string | undefined) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api.createDeployment(serviceId ?? ""),
    onSuccess: (deployment: Deployment) => {
      void client.invalidateQueries({ queryKey: keys.deployments(deployment.service_id) });
      void client.invalidateQueries({ queryKey: keys.instances(deployment.service_id) });
    },
  });
}

export function usePutVariable(serviceId: string | undefined) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (args: { key: string; value: string }) =>
      api.putVariable(serviceId ?? "", args.key, args.value),
    onSuccess: () => {
      if (serviceId) void client.invalidateQueries({ queryKey: keys.variables(serviceId) });
    },
  });
}

export function useDeleteVariable(serviceId: string | undefined) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (key: string) => api.deleteVariable(serviceId ?? "", key),
    onSuccess: () => {
      if (serviceId) void client.invalidateQueries({ queryKey: keys.variables(serviceId) });
    },
  });
}
