# Gocabservices

Gocabservices is a Django-based ride-hailing platform designed to support both riders and drivers through a managed booking lifecycle, driver onboarding, real-time location updates, and payment readiness.

## Overview

The application enables end-to-end local ride management with separate workflows for riders and drivers. Riders can request rides, review trip status, and complete payment flows. Drivers can register, submit verification documents, receive ride assignments, update location, and complete trips.

The codebase is built on Django with Channels for asynchronous communication, Redis for caching and session support, and options for PostgreSQL in production.

## Key Capabilities

- Rider booking and ride request workflow
- Driver registration, document upload, and approval state
- Real-time trip progress tracking
- Location updates for active drivers
- Trip acceptance, start, completion, and cancellation flows
- Fare estimation endpoint
- Payment initiation and success handling
- Admin site access for managing users and records

## Application Flow

1. Rider visits the homepage (`/`) and signs in.
2. Rider requests a ride using pickup and destination details.
3. Available drivers receive pending ride requests.
4. Driver accepts the ride and updates status to started.
5. Rider monitors ride status and payment state.
6. Driver completes the trip and payment is recorded.

## Folder Structure

- `Gocabservices/` - Django project configuration and settings
  - `settings/` - environment-specific Django settings
    - `base.py` — shared settings for all environments
    - `development.py` — local development settings
    - `production.py` — production deployment settings
    - `testing.py` — test runner settings
- `gocabapp/` - core application with business logic, routing, and presentation
  - `consumers/` - WebSocket consumers for real-time updates
  - `services/` - domain services and business operation helpers
  - `signals/` - event handlers and lifecycle hooks
  - `routing.py` - Channels routing configuration
  - `urls.py` - URL route definitions for HTTP views
  - `views/` - rider, driver, auth, and payment view handlers
  - `utils/` - shared utility functions
  - `templates/partials/` - reusable HTML template fragments
- `static/` - front-end assets and static resources
- `media/` - uploaded files for driver documents and images
- `requirements/` - dependency files for development, production, and testing
  - `base.txt` — core runtime dependencies
  - `development.txt` — development tools and formatters
  - `production.txt` — stable runtime dependencies for deployment
  - `testing.txt` — test dependencies and pytest plugins
- `scripts/` - utility scripts for infrastructure and maintenance
  - `redis_keepalive.py` — periodic Redis keepalive heartbeat script
- `docker-compose.yml` - local service orchestration for PostgreSQL, Redis, and the web server
- `Dockerfile` - production container image build instructions

## Routing and Views

Primary routes include:

- `/` — homepage
- `/signin/` — sign in page
- `/get-a-ride/` — rider request screen
- `/become-a-driver/` — driver onboarding form
- `/upgrade-to-driver/` — profile upgrade flow
- `/driver-dashboard/` — driver operations and status
- `/rider-dashboard/` — rider trip overview
- `/request_ride/` — submit ride request
- `/cancel-ride/<ride_id>/` — cancel ride
- `/driver/accept-ride/<ride_id>/` — accept pending ride
- `/driver/start-trip/<ride_id>/` — mark trip started
- `/driver/complete-trip/<ride_id>/` — complete trip
- `/api/estimate-fare/` — fare estimation endpoint
- `/initiate-payment/<ride_id>/` — payment initiation
- `/payment/success/<ride_id>/` — payment success callback
- `/driver/update-driver-location/` — driver location update

## Environment Configuration

The project depends on the following environment variables:

- `SECRET_KEY` — Django secret key
- `DEBUG` — development mode flag
- `DATABASE_URL` — database connection string
- `REDIS_URL` — Redis connection string
- `GOOGLE_MAPS_API_KEY` — Google Maps API key for location services
- `BASE_URL` — base site URL
- `PAYSTACK_SECRET_KEY` — payment gateway secret key
- `PAYSTACK_PUBLIC_KEY` — payment gateway public key
- `RESEND_API_KEY` — email/send integration key

### Recommended `.env` template

Create a `.env` file in the project root with values similar to:

```env
SECRET_KEY=replace-with-your-secret
DEBUG=True
DATABASE_URL=postgresql://user:password@localhost:5432/gocab
REDIS_URL=redis://localhost:6379/0
GOOGLE_MAPS_API_KEY=your-google-maps-key
BASE_URL=http://127.0.0.1:8000
PAYSTACK_SECRET_KEY=your-paystack-secret
PAYSTACK_PUBLIC_KEY=your-paystack-public
RESEND_API_KEY=your-resend-key
```

## Local Development

### Python setup

```bash
cd /Users/mymac/Documents/Mr Fix It All/MVP/Gocab/Gocabservices
python -m venv .venv
source .venv/bin/activate
pip install -r requirements/production.txt
```

### Database and cache

For local development you can use the Docker compose services or local installs.

#### Using Docker Compose

```bash
docker-compose up -d
```

This starts:

- PostgreSQL on port `5432`
- Redis on port `6379`
- Django application on port `8000`

#### Without Docker Compose

Start Redis locally:

```bash
redis-server
```

Then configure `DATABASE_URL` for your database and proceed.

### Migrations and static files

```bash
python manage.py migrate
python manage.py collectstatic --noinput
```

### Run the application

```bash
python manage.py runserver
```

Access the site at `http://127.0.0.1:8000`.

## Production Deployment

The project containerizes with the provided `Dockerfile` and is designed to run under Daphne.

Build and run production image:

```bash
docker build -t gocabservices .
docker run -p 8000:8000 --env-file .env gocabservices
```

The container uses `Gocabservices.settings.production` and collects static files during build.

## Testing

Run application tests:

```bash
python manage.py test
python manage.py test gocabapp
```

## Operational Notes

- `Gocabservices.settings.development` uses in-memory channels and local cache.
- Production should use Redis-backed channel layers and PostgreSQL.
- Static assets are served through Whitenoise in the container.
- Media uploads are stored in `media/` and should be mounted separately in production.

## Support and Maintenance

- Review `gocabapp/models.py` for core domain objects: Rider, Driver, RideRequest, Trip, Fare, Notification.
- Review `gocabapp/views/` for rider, driver, auth, and payment workflows.
- Review `docker-compose.yml` for local service dependencies and health checks.

## License

Proprietary. Use and distribution are subject to the terms of the owning organization.

## Support

For technical support or questions, please contact the development team.

---

**Note**: This is a ride-sharing application in active development. Features and configurations may evolve.
