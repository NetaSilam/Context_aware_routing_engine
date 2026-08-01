export type RouteJobShellStatus =
  | "empty"
  | "submitting"
  | "polling"
  | "completed"
  | "failed";

interface RouteJobShellProps {
  status: RouteJobShellStatus;
  error?: string;
}

const STATE_CONTENT: Record<
  RouteJobShellStatus,
  { heading: string; description: string }
> = {
  empty: {
    heading: "No route job yet",
    description: "Coordinate input and asynchronous submission will be added in a later ticket.",
  },
  submitting: {
    heading: "Submitting route job",
    description: "The request is being accepted and saved before background processing starts.",
  },
  polling: {
    heading: "Route job in progress",
    description: "The browser is checking the saved job until it reaches a terminal state.",
  },
  completed: {
    heading: "Route job completed",
    description: "The saved route result is ready to display.",
  },
  failed: {
    heading: "Route job failed",
    description: "The job reached a controlled failure state.",
  },
};

export default function RouteJobShell(props: RouteJobShellProps): JSX.Element {
  const content = STATE_CONTENT[props.status];

  return (
    <section
      className="filters-panel"
      aria-label="Route job"
      data-route-job-state={props.status}
    >
      <div className="filters-panel__heading">
        <p className="eyebrow">Route Job</p>
        <h2>{content.heading}</h2>
        <p>{props.status === "failed" && props.error ? props.error : content.description}</p>
      </div>
    </section>
  );
}
