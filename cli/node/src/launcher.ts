import * as p from "@clack/prompts";

export type LauncherActions = {
  chooseTarget: () => Promise<void>;
  deploy: () => Promise<void>;
  status: () => Promise<void>;
  logs: () => Promise<void>;
  services: () => Promise<void>;
  variables: () => Promise<void>;
  advisor: () => Promise<void>;
  signOut: () => Promise<void>;
};

type LauncherAction = Exclude<keyof LauncherActions, "chooseTarget" | "signOut"> | "choose-target" | "sign-out" | "exit";

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
  clear = () => console.clear(),
}: {
  actions: LauncherActions;
  clear?: () => void;
}): Promise<void> {
  clear();
  renderSplash();
  p.intro("Rudder control plane");

  while (true) {
    const selected = await p.select<LauncherAction>({
      message: "What would you like to do?",
      options: [
        { value: "choose-target", label: "Choose project/environment" },
        { value: "deploy", label: "Deploy" },
        { value: "status", label: "Status" },
        { value: "logs", label: "Logs" },
        { value: "services", label: "Services" },
        { value: "variables", label: "Variables" },
        { value: "advisor", label: "Advisor" },
        { value: "sign-out", label: "Sign out" },
        { value: "exit", label: "Exit" },
      ],
    });
    if (p.isCancel(selected)) {
      p.cancel("Launcher cancelled.");
      return;
    }
    if (selected === "exit") {
      p.outro("Until next time.");
      return;
    }

    const { action, label } = actionFor(selected, actions);
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

function actionFor(selected: Exclude<LauncherAction, "exit">, actions: LauncherActions): { action: () => Promise<void>; label: string } {
  if (selected === "choose-target") return { action: actions.chooseTarget, label: "Choose project/environment" };
  if (selected === "sign-out") return { action: actions.signOut, label: "Sign out" };
  return { action: actions[selected], label: selected[0]!.toUpperCase() + selected.slice(1) };
}

function renderSplash(): void {
  console.log("\x1b[48;5;235m\x1b[38;5;84m  RUDDER  \x1b[38;5;250mcontrol plane  \x1b[0m");
  console.log("\x1b[38;5;84m  ─────────────────────────────  \x1b[0m");
}
