# Spec Categories and Tags

Standard categories and tag guidelines for organizing specifications.

## Categories

| Category | Description | Typical Files |
|----------|-------------|---------------|
| `auth` | Authentication, authorization, sessions, security | `src/lib/auth/`, middleware, session handlers |
| `api` | API routes, endpoints, request/response handling | `src/app/api/`, route handlers, webhooks |
| `data` | Database schemas, models, migrations, data relationships | `prisma/schema`, models, migrations |
| `features` | User-facing features, UI components, pages | `src/components/`, `src/app/` pages |
| `infra` | Infrastructure, deployment, configuration | Config files, environment, CI/CD |
| `integration` | External services, third-party integrations | Service clients, webhooks, sync logic |
| `ui` | UI components, design system, user experience | `src/components/`, styles, themes |

## Standard Tags

### Security Tags
- `authentication` - Login, registration, identity verification
- `authorization` - Permissions, access control, roles
- `security` - General security-related features
- `encryption` - Data encryption, hashing
- `csrf` - Cross-site request forgery protection
- `cors` - Cross-origin resource sharing
- `rate-limiting` - Request throttling

### Data Tags
- `database` - Database operations
- `schema` - Data models and schemas
- `migration` - Database migrations
- `validation` - Input validation, data validation
- `caching` - Data caching strategies

### API Tags
- `rest` - REST API endpoints
- `graphql` - GraphQL schema and resolvers
- `webhooks` - Webhook handling
- `api-versioning` - API version management
- `pagination` - Result pagination

### Feature Tags
- `user-management` - User CRUD operations
- `notifications` - User notifications
- `file-upload` - File handling
- `search` - Search functionality
- `export` - Data export features
- `import` - Data import features

### Infrastructure Tags
- `deployment` - Deployment configuration
- `monitoring` - Logging, metrics, alerts
- `performance` - Performance optimization
- `testing` - Test infrastructure
- `ci-cd` - Continuous integration/deployment

### Integration Tags
- `payment` - Payment processing
- `email` - Email sending/management
- `sms` - SMS notifications
- `oauth` - OAuth provider integration
- `analytics` - Analytics integration

## Tagging Guidelines

1. **Be specific**: Use `rate-limiting` instead of generic `security`
2. **Multiple tags are fine**: A spec can have several relevant tags
3. **Include domain tags**: Tag with relevant domain (e.g., `payment`, `email`)
4. **Cross-reference**: If related to another spec, mention in Related Specs section

## Behaviors and categories

Categories and tags apply to the **spec**. A spec's `behaviors:` records do not
carry their own category — they inherit the spec's. When a behavior is verified
by a Gherkin feature, mirror the spec's category in the feature path
(`features/<category>/<name>.feature`) so the test tree parallels the spec tree.
Use the `testing` tag on a spec when its subject *is* test infrastructure, not
merely because it owns behaviors (every behavioral spec does).

## Category Decision Tree

```
Is it about logging in or permissions?
  → auth

Is it an API endpoint or route handler?
  → api

Is it about database tables or data models?
  → data

Is it something the user directly interacts with?
  → features

Is it about servers, deployment, or configuration?
  → infra

Is it connecting to an external service?
  → integration

Is it a reusable UI component?
  → ui
```

## Examples

### Passkey Authentication Spec
```yaml
category: auth
tags: [authentication, security, webauthn]
```

### Rate Limiting Spec
```yaml
category: api
tags: [rate-limiting, security, api]
```

### Team Photos Feature Spec
```yaml
category: features
tags: [file-upload, user-management, images]
```

### Stripe Integration Spec
```yaml
category: integration
tags: [payment, stripe, webhooks]
```

### Database Schema Spec
```yaml
category: data
tags: [database, schema, migration]
```

### CORS Configuration Spec
```yaml
category: api
tags: [cors, security, api]
```
