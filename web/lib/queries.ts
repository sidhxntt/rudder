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
  projects: ["projects"] as const,
  environments: (projectId: string) => ["environments", projectId] as const,
  services: (environmentId: string) => ["services", environmentId] as const,
  domains: (environmentId: string) => ["domains", environmentId] as const,
  deployments: (serviceId: string) => ["deployments", serviceId] as const,
  instances: (serviceId: string) => ["instances", serviceId] as const,
  variables: (serviceId: string) => ["variables", serviceId] as const,
  buildLog: (deploymentId: string) => ["build-log", deploymentId] as const,
};

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

/**
 * Build logs only. Runtime logs are Phase 5 (D4) and there is no view for them.
 * Polls until the log reports itself complete; the SSE endpoint from Phase 1
 * step 5 replaces the polling, not this call site.
 */
export function useBuildLog(deploymentId: string | undefined, complete: boolean) {
  return useQuery({
    queryKey: keys.buildLog(deploymentId ?? ""),
    queryFn: () => api.getBuildLog(deploymentId ?? ""),
    enabled: Boolean(deploymentId),
    refetchInterval: complete ? false : 700,
  });
}

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
