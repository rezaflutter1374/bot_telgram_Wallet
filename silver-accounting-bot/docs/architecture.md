# Architecture

Clean Architecture + DDD layering:

```mermaid
flowchart TB
  Telegram[Presentation: Telegram (Aiogram)]
  App[Application: Use Cases / DTOs]
  Domain[Domain: Entities / Services]
  Infra[Infrastructure: DB/Redis/Worker/Scheduler]

  Telegram --> App
  App --> Domain
  App --> Infra
  Infra --> App
```

Rules:

- Telegram handlers call only Application services/use-cases.
- Business rules live in Domain/Application, not in handlers.
- Infrastructure provides implementations (repositories, Redis cache, scheduler, worker).

