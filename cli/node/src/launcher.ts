import * as p from "@clack/prompts";

export type LauncherActions = {
  signIn: () => Promise<void>;
  chooseTarget: () => Promise<string | void>;
  deploy: () => Promise<void>;
  status: () => Promise<void>;
  logs: () => Promise<void>;
  services: () => Promise<void>;
  variables: () => Promise<void>;
  advisor: () => Promise<void>;
  signOut: () => Promise<void>;
};

type LauncherAction = Exclude<keyof LauncherActions, "signIn" | "chooseTarget" | "signOut"> | "choose-target" | "sign-out" | "exit";

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
  clear = () => console.clear(),
}: {
  actions: LauncherActions;
  authenticated?: boolean;
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
      return;
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
    if (selected === "choose-target") {
      try {
        const context = await action();
        if (context) {
          const spinner = p.spinner();
          spinner.start("Updating context");
          spinner.stop(context);
        }
      } catch (error) {
        throw error;
      }
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

function actionFor(selected: Exclude<LauncherAction, "exit">, actions: LauncherActions): { action: () => Promise<string | void>; label: string } {
  if (selected === "choose-target") return { action: actions.chooseTarget, label: "Choose project/environment" };
  if (selected === "sign-out") return { action: actions.signOut, label: "Sign out" };
  return { action: actions[selected], label: selected[0]!.toUpperCase() + selected.slice(1) };
}

function renderSplash(): void {
  console.log("\x1b[48;5;235m\x1b[38;5;84m  RUDDER  \x1b[38;5;250mcontrol plane  \x1b[0m");
  console.log("\x1b[38;5;84m  ─────────────────────────────  \x1b[0m");
}
