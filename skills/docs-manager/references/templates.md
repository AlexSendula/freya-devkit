# Documentation Templates

This file contains templates for each type of documentation. Use these as starting points and adapt to project needs.

## README.md (Documentation Index)

Located at `docs/README.md` - this is the main index that links to all documentation.

```markdown
# Project Documentation

Welcome to the [Project Name] documentation.

## Quick Links

| Document | Description |
|----------|-------------|
| [Project Overview](./project/PROJECT_OVERVIEW.md) | What this project is and who it's for |
| [Architecture](./project/ARCHITECTURE.md) | System design and structure |
| [Database](./project/DATABASE.md) | Schema, models, and relationships |
| [API Reference](./project/API.md) | Endpoints and request/response formats |
| [Environment](./project/ENVIRONMENT.md) | Configuration and environment variables |
| [Deployment](./project/DEPLOYMENT.md) | How to deploy to each environment |
| [Developer Guide](./project/DEVELOPER.md) | Setup and development conventions |
| [Testing](./project/TESTING.md) | Testing strategy and coverage |
| [Style Guide](./project/STYLE_GUIDE.md) | Coding standards |
| [Infrastructure](./project/INFRASTRUCTURE.md) | Hosting and infrastructure details |
| [Security](./project/SECURITY.md) | Security practices |
| [Troubleshooting](./project/TROUBLESHOOTING.md) | Common issues and solutions |

## Getting Started

New to the project? Start here:
1. Read [PROJECT_OVERVIEW.md](./project/PROJECT_OVERVIEW.md) to understand what we're building
2. Follow [DEVELOPER.md](./project/DEVELOPER.md) for setup instructions
3. Review [ARCHITECTURE.md](./project/ARCHITECTURE.md) to understand the system
4. Check [STYLE_GUIDE.md](./project/STYLE_GUIDE.md) for coding conventions

## Keeping Docs Updated

This documentation should be kept in sync with the codebase. After making significant changes:
\`\`\`bash
/docs-manager update
\`\`\`
```

---

## PROJECT_OVERVIEW.md

```markdown
# Project Overview

> Last updated: [Date]

## What is [Project Name]?

[1-2 sentence description of what this project is, e.g., "A restaurant website with online ordering and table reservations for local restaurants in Belgium."]

## Target Users

| User Type | Description | Key Needs |
|-----------|-------------|-----------|
| [User 1] | [Who they are] | [What they need from the system] |
| [User 2] | [Who they are] | [What they need from the system] |

## Core Features

1. **[Feature 1]** - [Brief description]
2. **[Feature 2]** - [Brief description]
3. **[Feature 3]** - [Brief description]

## Business Context

### Domain

[Describe the business domain, e.g., "Restaurant industry - focused on small to medium restaurants that want an online presence without commission-based platforms like UberEats."]

### Key Business Rules

| Rule | Description |
|------|-------------|
| [Rule 1] | [Business logic that affects implementation] |
| [Rule 2] | [Business logic that affects implementation] |

### Integrations

| Service | Purpose | Documentation |
|---------|---------|---------------|
| [Service 1] | [What it's used for] | [Link] |

## Project Status

- **Started:** [Date]
- **Current Version:** [Version]
- **Status:** [Active/In Development/Maintenance]

## Stakeholders

| Role | Name/Team | Contact |
|------|-----------|---------|
| [Role 1] | [Name] | [Contact method] |

## Related Documentation

- [Architecture](./ARCHITECTURE.md) - How the system is built
- [Developer Guide](./DEVELOPER.md) - How to work on this project
```

---

## ARCHITECTURE.md

```markdown
# Architecture

> Last updated: [Date]

## Overview

[High-level description of what the system does and its core purpose]

## System Diagram

\`\`\`mermaid
graph TD
    A[Client] --> B[API Gateway]
    B --> C[Auth Service]
    B --> D[Core Service]
    D --> E[(Database)]
    D --> F[Cache]
\`\`\`

## Core Components

### [Component 1 Name]
- **Location:** `src/components/component1/`
- **Purpose:** [What it does]
- **Key Files:**
  - `file1.ts` - [Description]
  - `file2.ts` - [Description]

### [Component 2 Name]
- **Location:** `src/components/component2/`
- **Purpose:** [What it does]

## Data Flow

[Describe how data moves through the system]

## Key Design Decisions

| Decision | Rationale | Alternatives Considered |
|----------|-----------|------------------------|
| [Decision 1] | [Why] | [What else was considered] |
| [Decision 2] | [Why] | [What else was considered] |

## External Dependencies

| Dependency | Purpose | Version | Documentation |
|------------|---------|---------|---------------|
| [Name] | [What it's used for] | [Version] | [Link] |

## Related Documentation

- [Database Schema](./DATABASE.md)
- [API Reference](./API.md)
```

---

## DATABASE.md

```markdown
# Database

> Last updated: [Date]

## Overview

[Database type and purpose, e.g., "PostgreSQL database for user data and application state"]

## Connection

\`\`\`bash
# Local development
psql -h localhost -U [user] -d [database]

# Production (example)
psql -h [host] -U [user] -d [database]
\`\`\`

## Entity Relationship Diagram

\`\`\`mermaid
erDiagram
    USER ||--o{ POST : creates
    USER ||--o{ COMMENT : writes
    POST ||--o{ COMMENT : has
    USER {
        uuid id PK
        string email UK
        string password_hash
        timestamp created_at
    }
    POST {
        uuid id PK
        uuid author_id FK
        string title
        text content
        timestamp published_at
    }
\`\`\`

## Tables

### users

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | uuid | PK, NOT NULL | Primary key |
| email | varchar(255) | UK, NOT NULL | User email |
| password_hash | varchar(255) | NOT NULL | Bcrypt hash |
| created_at | timestamp | NOT NULL, DEFAULT now() | Creation time |

**Indexes:**
- `users_email_idx` on `email` (for lookups)
- `users_created_at_idx` on `created_at` (for sorting)

### [Table 2]

[Same format as above]

## Relationships

| Relationship | Type | Description |
|--------------|------|-------------|
| User → Posts | One-to-Many | A user can have many posts |
| Post → Comments | One-to-Many | A post can have many comments |

## Migrations

Migrations are located in `prisma/migrations/` (or `migrations/`).

\`\`\`bash
# Create a new migration
npx prisma migrate dev --name describe_change

# Apply migrations
npx prisma migrate deploy

# Reset database (development only!)
npx prisma migrate reset
\`\`\`

## Query Patterns

### Common Queries

\`\`\`sql
-- Get user with their posts
SELECT u.*, p.*
FROM users u
LEFT JOIN posts p ON p.author_id = u.id
WHERE u.id = $1;

-- Search posts
SELECT * FROM posts
WHERE to_tsvector('english', title || ' ' || content) @@ to_tsquery($1);
\`\`\`

## Backup Strategy

[Describe backup frequency, retention, and restore procedures]

## Related Documentation

- [Architecture](./ARCHITECTURE.md)
- [API Reference](./API.md)
```

---

## API.md

```markdown
# API Reference

> Last updated: [Date]
> Base URL: `https://api.example.com/v1`

## Authentication

All API requests require a Bearer token:

\`\`\`bash
curl -H "Authorization: Bearer <token>" https://api.example.com/v1/users
\`\`\`

## Error Responses

All errors follow this format:

\`\`\`json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Email is required",
    "details": {}
  }
}
\`\`\`

## Endpoints

### Users

#### List Users

\`\`\`http
GET /users
\`\`\`

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| page | integer | No | Page number (default: 1) |
| limit | integer | No | Items per page (default: 20, max: 100) |
| search | string | No | Search by name or email |

**Response:**

\`\`\`json
{
  "data": [
    {
      "id": "uuid",
      "email": "user@example.com",
      "name": "John Doe",
      "created_at": "2024-01-15T10:30:00Z"
    }
  ],
  "pagination": {
    "page": 1,
    "limit": 20,
    "total": 150,
    "total_pages": 8
  }
}
\`\`\`

#### Create User

\`\`\`http
POST /users
\`\`\`

**Request Body:**

\`\`\`json
{
  "email": "user@example.com",
  "name": "John Doe",
  "password": "securepassword123"
}
\`\`\`

**Response:** `201 Created`

\`\`\`json
{
  "id": "uuid",
  "email": "user@example.com",
  "name": "John Doe",
  "created_at": "2024-01-15T10:30:00Z"
}
\`\`\`

### [Resource 2]

[Same format as above]

## Rate Limiting

- **Standard endpoints:** 100 requests/minute
- **Auth endpoints:** 10 requests/minute

Rate limit headers are included in all responses:
\`\`\`
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1705312800
\`\`\`

## Versioning

The API uses URL versioning (`/v1/`, `/v2/`). Breaking changes result in a new version.

## Related Documentation

- [Authentication Flow](./AUTHENTICATION.md) (if separate)
- [Database Schema](./DATABASE.md)
```

---

## DEPLOYMENT.md

```markdown
# Deployment

> Last updated: [Date]

## Environments

| Environment | URL | Purpose |
|-------------|-----|---------|
| Development | `https://dev.example.com` | Feature testing |
| Staging | `https://staging.example.com` | Pre-production testing |
| Production | `https://example.com` | Live users |

## Prerequisites

- [ ] Docker installed
- [ ] Access to [hosting provider]
- [ ] Environment variables configured
- [ ] Database migrations ready

## Deployment Methods

### Docker (Recommended)

\`\`\`bash
# Build image
docker build -t myapp:latest .

# Run locally for testing
docker run -p 3000:3000 --env-file .env myapp:latest

# Push to registry
docker push registry.example.com/myapp:latest
\`\`\`

### Dokploy

\`\`\`bash
# Connect to Dokploy server
ssh user@dokploy.example.com

# Deploy via Dokploy CLI
dokploy deploy myapp --env production
\`\`\`

### Manual Deployment

[Step-by-step instructions if applicable]

## Environment Variables

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| DATABASE_URL | Yes | PostgreSQL connection string | `postgresql://...` |
| JWT_SECRET | Yes | Secret for JWT signing | `random-32-char-string` |
| REDIS_URL | No | Redis connection (optional) | `redis://localhost:6379` |

## Deployment Checklist

### Pre-Deployment
- [ ] All tests passing
- [ ] Database migrations tested
- [ ] Environment variables set
- [ ] Backup created

### During Deployment
- [ ] Monitor logs for errors
- [ ] Verify health check endpoints
- [ ] Check database connectivity

### Post-Deployment
- [ ] Smoke tests passing
- [ ] Monitor error rates
- [ ] Verify key user flows

## Rollback Procedure

\`\`\`bash
# Docker rollback
kubectl rollout undo deployment/myapp

# Dokploy rollback
dokploy rollback myapp --version previous
\`\`\`

## Health Checks

- **Liveness:** `GET /health/live` → 200 OK
- **Readiness:** `GET /health/ready` → 200 OK (includes DB check)

## Monitoring

[Link to monitoring dashboard or describe how to access logs]

## Related Documentation

- [Infrastructure](./INFRASTRUCTURE.md)
- [Developer Guide](./DEVELOPER.md)
```

---

## DEVELOPER.md

```markdown
# Developer Guide

> Last updated: [Date]

## Quick Start

\`\`\`bash
# Clone and setup
git clone [repo-url]
cd [project-name]
npm install

# Setup environment
cp .env.example .env
# Edit .env with your values

# Start development
npm run dev
\`\`\`

## Prerequisites

- Node.js 20+
- PostgreSQL 15+
- Redis (optional, for caching)

## Project Structure

\`\`\`
src/
├── components/     # React components
├── lib/           # Utility libraries
├── pages/         # Next.js pages
├── prisma/        # Database schema and migrations
├── styles/        # Global styles
└── types/         # TypeScript types
\`\`\`

## Available Scripts

| Command | Description |
|---------|-------------|
| `npm run dev` | Start development server |
| `npm run build` | Build for production |
| `npm run test` | Run tests |
| `npm run lint` | Run ESLint |
| `npm run db:migrate` | Run database migrations |
| `npm run db:studio` | Open Prisma Studio |

## Development Workflow

### 1. Create a Branch

\`\`\`bash
git checkout -b feature/my-feature
\`\`\`

### 2. Make Changes

Write code, following the [Style Guide](./STYLE_GUIDE.md).

### 3. Test Your Changes

\`\`\`bash
npm run test
npm run lint
\`\`\`

### 4. Create a Pull Request

- Reference any related issues
- Describe your changes
- Include screenshots for UI changes

## Testing

### Unit Tests

\`\`\`bash
# Run all tests
npm run test

# Run specific file
npm run test -- path/to/test.ts

# Run with coverage
npm run test:coverage
\`\`\`

### Integration Tests

\`\`\`bash
# Requires running database
npm run test:integration
\`\`\`

## Database Development

### Create a Migration

\`\`\`bash
# After modifying schema.prisma
npx prisma migrate dev --name describe_change
\`\`\`

### Seed Data

\`\`\`bash
npm run db:seed
\`\`\`

## Debugging

[Debugging tips, how to attach debuggers, etc.]

## Common Issues

### "Database connection failed"
- Check if PostgreSQL is running
- Verify DATABASE_URL in .env

### "Port 3000 already in use"
\`\`\`bash
# Find and kill process
lsof -i :3000
kill -9 [PID]
\`\`\`

## Related Documentation

- [Style Guide](./STYLE_GUIDE.md)
- [Architecture](./ARCHITECTURE.md)
```

---

## STYLE_GUIDE.md

```markdown
# Style Guide

> Last updated: [Date]

## General Principles

1. **Readability first** - Code is read more than written
2. **Consistency** - Follow existing patterns
3. **Explicit over implicit** - Be clear about intent

## Formatting

### Indentation

- Use **2 spaces** for indentation
- No tabs

### Line Length

- Maximum **100 characters** per line
- Break long strings and function calls

### Quotes

- Use **single quotes** for strings in JavaScript/TypeScript
- Use double quotes only when string contains single quotes

\`\`\`javascript
// Good
const name = 'John';
const message = "It's a test";

// Bad
const name = "John";
\`\`\`

## Naming Conventions

| Type | Convention | Example |
|------|------------|---------|
| Variables | camelCase | `userName` |
| Constants | UPPER_SNAKE | `MAX_RETRIES` |
| Functions | camelCase | `getUserById` |
| Classes | PascalCase | `UserService` |
| Components | PascalCase | `UserProfile` |
| Files (components) | PascalCase | `UserProfile.tsx` |
| Files (utilities) | kebab-case | `date-utils.ts` |
| CSS classes | kebab-case | `user-profile-card` |

## TypeScript

### Type Definitions

\`\`\`typescript
// Prefer interfaces for objects
interface User {
  id: string;
  name: string;
  email: string;
}

// Use type for unions/intersections
type Status = 'active' | 'inactive' | 'pending';
\`\`\`

### Avoid `any`

\`\`\`typescript
// Bad
function process(data: any) { ... }

// Good
function process(data: unknown) {
  if (typeof data === 'string') { ... }
}
\`\`\`

## React/Components

### Component Structure

\`\`\`typescript
// 1. Imports
import { useState } from 'react';

// 2. Types
interface Props {
  title: string;
}

// 3. Component
export function MyComponent({ title }: Props) {
  // Hooks at top
  const [count, setCount] = useState(0);

  // Event handlers
  const handleClick = () => setCount(c => c + 1);

  // Render
  return <div onClick={handleClick}>{title}: {count}</div>;
}
\`\`\`

### Component Organization

- One component per file
- Keep components small (< 200 lines)
- Extract reusable logic to hooks

## CSS/Styling

[Project-specific styling conventions]

## Git Conventions

### Commit Messages

Format: `type(scope): description`

Types:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation
- `refactor`: Code refactoring
- `test`: Adding tests
- `chore`: Maintenance

\`\`\`
feat(auth): add password reset flow
fix(api): handle null user in response
docs(readme): update installation steps
\`\`\`

### Branch Names

- `feature/description` - New features
- `fix/description` - Bug fixes
- `refactor/description` - Refactoring

## Linting

Configuration is in `.eslintrc.js` and `.prettierrc`.

\`\`\`bash
# Check for issues
npm run lint

# Auto-fix
npm run lint:fix
\`\`\`

## Related Documentation

- [Developer Guide](./DEVELOPER.md)
```

---

## INFRASTRUCTURE.md

```markdown
# Infrastructure

> Last updated: [Date]

## Overview

[High-level description of infrastructure, e.g., "Self-hosted on Hetzner using Dokploy for container orchestration"]

## Hosting Provider

### Primary: Hetzner

| Server | Type | Location | Purpose |
|--------|------|----------|---------|
| prod-1 | CX41 | Falkenstein | Production apps |
| prod-2 | CX31 | Falkenstein | Database |
| staging | CX21 | Falkenstein | Staging environment |

### Backup: [If applicable]

## Container Orchestration

### Dokploy

- **URL:** `https://dokploy.example.com`
- **Version:** 1.x.x
- **Access:** Contact [team member] for credentials

**Deployed Applications:**
| App | Domain | Port | Notes |
|-----|--------|------|-------|
| frontend | app.example.com | 3000 | Next.js app |
| api | api.example.com | 4000 | Node.js API |
| database | - | 5432 | PostgreSQL |

## DNS Configuration

Managed through [provider, e.g., Cloudflare, Route53]

| Record | Type | Value | Notes |
|--------|------|-------|-------|
| example.com | A | 1.2.3.4 | Main domain |
| api.example.com | CNAME | example.com | API subdomain |
| staging.example.com | A | 5.6.7.8 | Staging |

### Client DNS Configurations

[For clients managing their own DNS]

| Client | Domain | Records | Contact |
|--------|--------|---------|---------|
| Client A | client-a.com | A record to our IP | IT Team |

## SSL Certificates

- **Provider:** Let's Encrypt (via Dokploy)
- **Auto-renewal:** Enabled
- **Domains:** All production domains

## Database Infrastructure

### PostgreSQL

- **Version:** 15
- **Hosted:** Dedicated server (prod-2)
- **Backup:** Daily at 2:00 AM UTC
- **Retention:** 30 days

### Redis

- **Version:** 7
- **Hosted:** Same as PostgreSQL
- **Purpose:** Session storage, caching

## Monitoring & Logging

### Monitoring

- **Tool:** [e.g., Grafana, Uptime Kuma]
- **Dashboard:** `https://monitoring.example.com`
- **Alerts:** Configured for downtime, high CPU, low disk

### Logging

- **Tool:** [e.g., Loki, Papertrail]
- **Retention:** 14 days
- **Access:** [How to access logs]

## Backup Strategy

| What | Frequency | Retention | Location |
|------|-----------|-----------|----------|
| Database | Daily | 30 days | S3 bucket |
| Files | Daily | 7 days | S3 bucket |
| Configs | On change | Forever | Git repo |

## Access & Security

### Server Access

\`\`\`bash
# SSH into production
ssh user@prod-1.example.com
\`\`\`

### Firewall Rules

- SSH: Port 22 (restricted IPs)
- HTTP/HTTPS: Ports 80, 443 (open)
- Database: Port 5432 (internal only)

## Scaling Considerations

[Notes on how to scale, when to add resources, etc.]

## Related Documentation

- [Deployment](./DEPLOYMENT.md)
- [Security](./SECURITY.md)
```

---

## SECURITY.md

```markdown
# Security

> Last updated: [Date]

## Overview

This document outlines security practices and considerations for [Project Name].

## Authentication

### User Authentication

- **Method:** JWT tokens with refresh tokens
- **Token Expiry:** Access: 15 min, Refresh: 7 days
- **Password Storage:** bcrypt with cost factor 12

### API Authentication

- **Method:** API keys for external services
- **Key Rotation:** Every 90 days

## Authorization

### Role-Based Access Control (RBAC)

| Role | Permissions |
|------|-------------|
| Admin | Full access |
| Editor | Read/Write |
| Viewer | Read only |

## Data Protection

### Sensitive Data

| Data Type | Storage | Encryption |
|-----------|---------|------------|
| Passwords | Database | bcrypt |
| API Keys | Environment | At rest |
| PII | Database | TLS in transit |

### Data Retention

- User data: Deleted on account deletion
- Logs: 14 days
- Backups: 30 days

## Security Headers

All responses include:

\`\`\`
Strict-Transport-Security: max-age=31536000; includeSubDomains
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Content-Security-Policy: default-src 'self'
\`\`\`

## Dependency Security

\`\`\`bash
# Check for vulnerabilities
npm audit

# Fix automatically
npm audit fix
\`\`\`

Run in CI pipeline for automatic alerts.

## Incident Response

### Reporting

Report security issues to: security@example.com

### Response Process

1. Acknowledge report within 24 hours
2. Assess severity
3. Develop fix
4. Deploy patch
5. Post-mortem

## Security Checklist

- [ ] HTTPS enforced
- [ ] Input validation on all endpoints
- [ ] SQL injection prevention (parameterized queries)
- [ ] XSS prevention (output encoding)
- [ ] CSRF tokens on state-changing operations
- [ ] Rate limiting enabled
- [ ] Dependency audits in CI
- [ ] Secrets not in git
- [ ] Error messages don't leak info

## Related Documentation

- [Infrastructure](./INFRASTRUCTURE.md)
- [API Reference](./API.md)
```

---

## CHANGELOG.md

```markdown
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- [New features not yet released]

### Changed
- [Changes not yet released]

## [1.2.0] - 2024-01-15

### Added
- Password reset functionality
- Email verification on signup

### Changed
- Improved search performance by 50%

### Fixed
- Session expiration bug
- Mobile layout issues

### Security
- Updated dependencies to fix CVE-2024-XXXXX

## [1.1.0] - 2024-01-01

### Added
- User profile editing
- Dark mode support

### Fixed
- Login redirect loop

## [1.0.0] - 2023-12-15

### Added
- Initial release
- User authentication
- Basic CRUD operations

[Unreleased]: https://github.com/org/repo/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/org/repo/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/org/repo/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/org/repo/releases/tag/v1.0.0
```

---

## ENVIRONMENT.md

```markdown
# Environment Configuration

> Last updated: [Date]

## Overview

This document describes all environment variables and configuration needed to run the application.

## Quick Setup

\`\`\`bash
# Copy example env file
cp .env.example .env

# Edit with your values
nano .env
\`\`\`

## Environment Variables

### Required Variables

| Variable | Description | Example | Where to get |
|----------|-------------|---------|--------------|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://user:pass@localhost:5432/db` | Local DB or hosting provider |
| `NEXTAUTH_SECRET` | Secret for NextAuth.js | `random-32-char-string` | Generate with `openssl rand -base64 32` |
| `NEXTAUTH_URL` | Base URL of your app | `http://localhost:3000` | Your app's URL |

### Optional Variables

| Variable | Description | Default | When needed |
|----------|-------------|---------|-------------|
| `REDIS_URL` | Redis connection for caching | None | When using caching |
| `SMTP_HOST` | Email server host | None | When sending emails |
| `SENTRY_DSN` | Sentry error tracking | None | When using Sentry |

### Feature Flags

| Variable | Description | Default |
|----------|-------------|---------|
| `FEATURE_NEW_UI` | Enable new UI beta | `false` |
| `FEATURE_ANALYTICS` | Enable analytics tracking | `false` |

## Secrets Management

### Development

Store secrets in `.env` (never commit this file):
\`\`\`
# .env
DATABASE_URL=postgresql://...
NEXTAUTH_SECRET=your-secret-here
\`\`\`

### Production

Secrets are managed through [Dokploy environment variables / AWS Secrets Manager / etc.]

\`\`\`bash
# Dokploy: Set via dashboard or CLI
dokploy env set myapp NEXTAUTH_SECRET "value"

# Or use secrets file
dokploy secrets:upload myapp ./secrets.txt
\`\`\`

## Environment-Specific Configuration

| Variable | Development | Staging | Production |
|----------|-------------|---------|------------|
| `NODE_ENV` | `development` | `staging` | `production` |
| `LOG_LEVEL` | `debug` | `info` | `warn` |
| `DATABASE_URL` | Local DB | Staging DB | Prod DB |

## Configuration Files

| File | Purpose |
|------|---------|
| `.env.example` | Template with all required variables |
| `.env.local` | Local overrides (git-ignored) |
| `.env.test` | Test environment configuration |
| `config/` | Application config files |

## Troubleshooting

### "DATABASE_URL is not defined"
1. Check `.env` file exists
2. Verify variable name matches exactly
3. Restart the development server

### "Invalid DATABASE_URL format"
Ensure the format is: `postgresql://[user]:[password]@[host]:[port]/[database]`

## Related Documentation

- [Developer Guide](./DEVELOPER.md) - Setup instructions
- [Deployment](./DEPLOYMENT.md) - Production configuration
- [Infrastructure](./INFRASTRUCTURE.md) - Where secrets are stored
```

---

## TESTING.md

```markdown
# Testing Guide

> Last updated: [Date]

## Overview

This document describes the testing strategy, coverage requirements, and common patterns for this project.

## Testing Stack

| Tool | Purpose |
|------|---------|
| [Jest/Vitest] | Unit test runner |
| [Testing Library] | React component testing |
| [Playwright/Cypress] | E2E testing |
| [MSW] | API mocking |

## Running Tests

\`\`\`bash
# Run all tests
npm run test

# Run in watch mode
npm run test:watch

# Run with coverage
npm run test:coverage

# Run specific test file
npm run test -- path/to/test.ts

# Run E2E tests
npm run test:e2e
\`\`\`

## Test Organization

\`\`\`
tests/
├── unit/           # Unit tests for individual functions
├── integration/    # Integration tests for API/routes
├── e2e/            # End-to-end tests
└── fixtures/       # Test data and mocks
\`\`\`

## Coverage Requirements

| Type | Minimum | Target |
|------|---------|--------|
| Lines | 70% | 80% |
| Branches | 60% | 75% |
| Functions | 70% | 85% |

Run `npm run test:coverage` to check current coverage.

## Unit Tests

### Example: Testing a utility function

\`\`\`typescript
// utils/date.test.ts
import { formatDate } from './date';

describe('formatDate', () => {
  it('formats a date in DD/MM/YYYY format', () => {
    const date = new Date('2024-01-15');
    expect(formatDate(date)).toBe('15/01/2024');
  });

  it('handles invalid dates', () => {
    expect(formatDate(null)).toBe('Invalid date');
  });
});
\`\`\`

### Example: Testing a React component

\`\`\`typescript
// components/Button.test.tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Button } from './Button';

describe('Button', () => {
  it('renders with text', () => {
    render(<Button>Click me</Button>);
    expect(screen.getByText('Click me')).toBeInTheDocument();
  });

  it('calls onClick when clicked', async () => {
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Click me</Button>);

    await userEvent.click(screen.getByText('Click me'));
    expect(onClick).toHaveBeenCalledOnce();
  });
});
\`\`\`

## Integration Tests

### Example: Testing an API route

\`\`\`typescript
// tests/integration/api/users.test.ts
import { POST } from '@/app/api/users/route';

describe('POST /api/users', () => {
  it('creates a new user', async () => {
    const request = new Request('http://localhost/api/users', {
      method: 'POST',
      body: JSON.stringify({ email: 'test@example.com', name: 'Test' }),
    });

    const response = await POST(request);
    const data = await response.json();

    expect(response.status).toBe(201);
    expect(data.email).toBe('test@example.com');
  });
});
\`\`\`

## E2E Tests

### Example: User login flow

\`\`\`typescript
// tests/e2e/login.spec.ts
import { test, expect } from '@playwright/test';

test('user can login', async ({ page }) => {
  await page.goto('/login');

  await page.fill('[name="email"]', 'user@example.com');
  await page.fill('[name="password"]', 'password123');
  await page.click('button[type="submit"]');

  await expect(page).toHaveURL('/dashboard');
});
\`\`\`

## Test Data

### Fixtures

\`\`\`typescript
// tests/fixtures/user.ts
export const mockUser = {
  id: 'test-user-id',
  email: 'test@example.com',
  name: 'Test User',
};

export const mockAdmin = {
  id: 'admin-id',
  email: 'admin@example.com',
  name: 'Admin User',
  role: 'admin',
};
\`\`\`

### Database Seeding

\`\`\`bash
# Seed test database
npm run db:seed:test
\`\`\`

## Mocking

### API Mocking with MSW

\`\`\`typescript
// tests/mocks/handlers.ts
import { http, HttpResponse } from 'msw';

export const handlers = [
  http.get('/api/users', () => {
    return HttpResponse.json([{ id: '1', name: 'Test User' }]);
  }),
];
\`\`\`

## CI/CD Integration

Tests run automatically in GitHub Actions:

\`\`\`yaml
# .github/workflows/test.yml
- name: Run tests
  run: npm run test:coverage

- name: Upload coverage
  uses: codecov/codecov-action@v3
\`\`\`

## Best Practices

1. **One assertion per test** - Keep tests focused
2. **Descriptive test names** - Should read like documentation
3. **Test behavior, not implementation** - Focus on what, not how
4. **Keep tests isolated** - No dependencies between tests
5. **Use fixtures** - Don't duplicate test data

## Related Documentation

- [Developer Guide](./DEVELOPER.md) - How to run tests locally
- [API Reference](./API.md) - What endpoints to test
- [Style Guide](./STYLE_GUIDE.md) - Code conventions for tests
```

---

## TROUBLESHOOTING.md

```markdown
# Troubleshooting Guide

> Last updated: [Date]

## Common Issues

### Development

#### "Module not found" errors

**Symptoms:** Error like `Cannot find module '@/components/Button'`

**Solutions:**
1. Check the import path is correct
2. Verify `tsconfig.json` paths configuration
3. Restart TypeScript server: `Cmd+Shift+P` → "TypeScript: Restart TS Server"
4. Clear Next.js cache: `rm -rf .next`

#### Database connection issues

**Symptoms:** `ECONNREFUSED`, `Connection refused`, or timeout errors

**Solutions:**
1. Check if PostgreSQL is running:
   \`\`\`bash
   # macOS
   brew services list
   brew services start postgresql@15

   # Linux
   sudo systemctl status postgresql
   sudo systemctl start postgresql
   \`\`\`
2. Verify `DATABASE_URL` in `.env`
3. Check database exists: `psql -l`
4. Check firewall isn't blocking port 5432

#### "Port 3000 already in use"

**Symptoms:** `Error: listen EADDRINUSE: address already in use :::3000`

**Solutions:**
\`\`\`bash
# Find and kill process
lsof -i :3000
kill -9 <PID>

# Or use a different port
PORT=3001 npm run dev
\`\`\`

#### npm install hangs or fails

**Symptoms:** Install process freezes or errors out

**Solutions:**
1. Clear npm cache: `npm cache clean --force`
2. Delete node_modules: `rm -rf node_modules && npm install`
3. Check Node version: `node --version` (should match `.nvmrc`)
4. Try with different registry: `npm install --registry https://registry.npmmirror.com`

### Build & Deployment

#### Build fails with memory error

**Symptoms:** `JavaScript heap out of memory`

**Solutions:**
\`\`\`bash
# Increase Node memory limit
NODE_OPTIONS="--max-old-space-size=4096" npm run build
\`\`\`

#### Environment variables not loaded

**Symptoms:** Variables work locally but not in production

**Solutions:**
1. Check variables are set in Dokploy/hosting dashboard
2. Verify variable names match exactly (case-sensitive)
3. Redeploy after adding new variables
4. Check `.env` file is NOT committed (should be in `.gitignore`)

#### Docker build fails

**Symptoms:** Docker build process errors

**Solutions:**
1. Check Dockerfile syntax
2. Ensure all dependencies are in `package.json`
3. Try building locally first: `docker build -t test .`
4. Check disk space: `df -h`

### Runtime Errors

#### "Hydration failed" (React/Next.js)

**Symptoms:** `Hydration failed because the server rendered HTML didn't match the client`

**Solutions:**
1. Check for browser-only APIs during render (use `useEffect`)
2. Ensure dates/random numbers are consistent
3. Check for mismatched HTML structure

#### Authentication redirects not working

**Symptoms:** Login succeeds but redirects to wrong page

**Solutions:**
1. Check `NEXTAUTH_URL` matches your actual URL
2. Verify callback URLs in auth configuration
3. Clear browser cookies and try again
4. Check middleware isn't interfering

#### API returns 500 errors

**Symptoms:** Internal server error from API routes

**Solutions:**
1. Check server logs: `docker logs <container>`
2. Look for unhandled promise rejections
3. Verify database connectivity
4. Check environment variables are loaded

### Database Issues

#### Migration fails

**Symptoms:** `Migration failed to apply`

**Solutions:**
\`\`\`bash
# Check migration status
npx prisma migrate status

# Force reset (development only!)
npx prisma migrate reset

# Mark migration as applied (if already in DB)
npx prisma migrate resolve --applied <migration_name>
\`\`\`

#### Slow queries

**Symptoms:** API responses are slow, timeouts

**Solutions:**
1. Check missing indexes: `EXPLAIN ANALYZE <query>`
2. Review query patterns in [DATABASE.md](./DATABASE.md)
3. Consider adding caching (Redis)
4. Check database resource usage

## Debugging Tips

### Enable Debug Logging

\`\`\`bash
# Enable all debug logs
DEBUG=* npm run dev

# Enable specific namespace
DEBUG=app:* npm run dev

# Next.js specific
NEXT_DEBUG=1 npm run dev
\`\`\`

### Check Logs

\`\`\`bash
# Dokploy logs
dokploy logs myapp --follow

# Docker logs
docker logs <container> --follow --tail 100

# Application logs
tail -f logs/app.log
\`\`\`

### Database Debugging

\`\`\`bash
# Connect to database
psql $DATABASE_URL

# Check running queries
SELECT * FROM pg_stat_activity;

# Check table sizes
SELECT relname, pg_size_pretty(pg_total_relation_size(relid))
FROM pg_catalog.pg_statio_user_tables;
\`\`\`

## Getting Help

1. Check this troubleshooting guide
2. Search existing GitHub issues
3. Check [INFRASTRUCTURE.md](./INFRASTRUCTURE.md) for environment details
4. Contact: [support contact or team chat]

## Related Documentation

- [Developer Guide](./DEVELOPER.md) - Setup and common commands
- [Infrastructure](./INFRASTRUCTURE.md) - Server and deployment info
- [Environment](./ENVIRONMENT.md) - Configuration variables
```
```
