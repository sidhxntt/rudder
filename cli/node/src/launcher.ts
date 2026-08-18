import * as p from "@clack/prompts";
import { CliCancellationError } from "./errors.js";

export type LauncherActions = {
  signIn: () => Promise<void>;
  chooseProject?: () => Promise<string | void>;
  deploy: () => Promise<void>;
  status: () => Promise<void>;
  logs: () => Promise<void>;
  services: () => Promise<void>;
  variables: () => Promise<void>;
  advisor: () => Promise<void>;
  signOut: () => Promise<void>;
};

export type StatusActions = {
  compact: () => Promise<void>;
  detailed: () => Promise<void>;
  summary: () => Promise<void>;
};

type LauncherAction = Exclude<keyof LauncherActions, "signIn" | "chooseProject" | "signOut"> | "back" | "sign-out" | "exit";

export function canLaunchLauncher({
  hasArgs,
  json,
  noInteractive,
  stdinTTY,
  stdoutTTY,
}: {
  hasArgs: boolean;
  json: boolean;
  noInteractive: boolean;
  stdinTTY: boolean;
  stdoutTTY: boolean;
}): boolean {
  return !hasArgs && !json && !noInteractive && stdinTTY && stdoutTTY;
}

export async function runLauncher({
  actions,
  authenticated = true,
  projectSelected = true,
  clear = () => console.clear(),
}: {
  actions: LauncherActions;
  authenticated?: boolean;
  projectSelected?: boolean;
  clear?: () => void;
}): Promise<void> {
  clear();
  renderSplash();
  p.intro("Rudder control plane");

  if (!authenticated) {
    const signIn = await p.select<"sign-in" | "exit">({
      message: "Welcome to Rudder",
      options: [
        { value: "sign-in", label: "Sign in with GitHub", hint: "Connect your Rudder workspace" },
        { value: "exit", label: "Exit" },
      ],
    });
    if (p.isCancel(signIn)) {
      p.cancel("Sign-in cancelled.");
      throw new CliCancellationError();
    }
    if (signIn === "exit") {
      p.outro("Until next time.");
      return;
    }
    const spinner = p.spinner();
    spinner.start("Opening GitHub sign-in");
    try {
      await actions.signIn();
      spinner.stop("GitHub connected");
    } catch (error) {
      spinner.stop("GitHub sign-in failed");
      throw error;
    }
  }

  if (!projectSelected) {
    if (!actions.chooseProject) throw new Error("Project onboarding is unavailable.");
    const context = await actions.chooseProject();
    if (!context) {
      p.outro("Until next time.");
      return;
    }
    p.note(context, "Project selected");
  }

  while (true) {
    const selected = await p.select<LauncherAction>({
      message: "What would you like to do?",
      options: [
        { value: "deploy", label: "Deploy" },
        { value: "status", label: "Status" },
        { value: "logs", label: "Logs" },
        { value: "services", label: "Services" },
        { value: "variables", label: "Variables" },
        { value: "advisor", label: "Advisor" },
        { value: "back", label: "Back to project selection" },
        { value: "sign-out", label: "Sign out" },
        { value: "exit", label: "Exit" },
      ],
    });
    if (p.isCancel(selected)) {
      p.cancel("Launcher cancelled.");
      throw new CliCancellationError();
    }
    if (selected === "exit") {
      p.outro("Until next time.");
      return;
    }

    const { action, label } = actionFor(selected, actions);
    if (selected === "back") {
      if (!actions.chooseProject) throw new Error("Project selection is unavailable.");
      const context = await actions.chooseProject();
      if (context) p.note(context, "Project selected");
      continue;
    }
    if (selected === "status" || selected === "logs") {
      await actions[selected]();
      continue;
    }
    const spinner = p.spinner();
    spinner.start(label);
    try {
      await action();
      spinner.stop(`${label} complete`);
    } catch (error) {
      spinner.stop(`${label} failed`);
      throw error;
    }
    if (selected === "sign-out") {
      p.outro("Signed out.");
      return;
    }
  }
}

/** Let an operator choose the level of detail without losing their launcher context. */
export async function runStatusMenu(actions: StatusActions): Promise<void> {
  while (true) {
    const selected = await p.select<"compact" | "detailed" | "summary" | "back">({
      message: "Status view",
      options: [
        { value: "compact", label: "Compact status", hint: "Live services and latest release" },
        { value: "detailed", label: "Detailed status", hint: "Full deployment and instance data" },
        { value: "summary", label: "AI summary", hint: "Explain current state and next steps" },
        { value: "back", label: "Back to main menu" },
      ],
    });
    if (p.isCancel(selected)) {
      p.cancel("Status selection cancelled.");
      throw new CliCancellationError();
    }
    if (selected === "back") return;
    const action = actions[selected];
    const labels = { compact: "Loading compact status", detailed: "Loading detailed status", summary: "Preparing AI summary" };
    const spinner = p.spinner();
    spinner.start(labels[selected]);
    try {
      await action();
      spinner.stop("Status ready");
    } catch (error) {
      spinner.stop("Status unavailable");
      throw error;
    }
  }
}

function actionFor(selected: Exclude<LauncherAction, "exit">, actions: LauncherActions): { action: () => Promise<string | void>; label: string } {
  if (selected === "back") return { action: async () => undefined, label: "Back to project selection" };
  if (selected === "sign-out") return { action: actions.signOut, label: "Sign out" };
  return { action: actions[selected], label: selected[0]!.toUpperCase() + selected.slice(1) };
}

export function renderSplash(): void {
  const emerald = "\x1b[38;5;84m";
  const ink = "\x1b[38;5;255m";
  const muted = "\x1b[38;5;245m";
  const reset = "\x1b[0m";
  const interiorWidth = 42;
  const title = "RUDDER".padStart(24).padEnd(interiorWidth);
  const border = `┌${"─".repeat(interiorWidth)}┐`;
  const divider = "─".repeat(interiorWidth + 2);
  console.log(`${emerald}
  ${border}
  │${title}│
  └${"─".repeat(interiorWidth)}┘${reset}
  ${ink}DEPLOYMENT CONTROL PLANE${reset}
  ${muted}GitHub-authenticated workspace · visible releases · local control${reset}
  ${emerald}${divider}${reset}`);
}
