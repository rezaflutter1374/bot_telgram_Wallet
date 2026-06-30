from __future__ import annotations

from arq import run_worker

from infrastructure.tasks.tasks import WorkerSettings


def main() -> None:
    run_worker(WorkerSettings)


if __name__ == "__main__":
    main()

