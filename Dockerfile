FROM node:22-alpine AS css
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY tailwind.config.cjs ./
COPY templates ./templates
COPY static/js ./static/js
COPY static/css/tailwind.css ./static/css/tailwind.css
RUN npm run build:css

FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --system app \
    && useradd --system --gid app --home-dir /app app
COPY . .
COPY --from=css /app/static/css/utilities.css ./static/css/utilities.css
RUN mkdir -p /app/media /app/private_documents /app/staticfiles \
    && chown -R app:app /app/media /app/private_documents /app/staticfiles
USER app
EXPOSE 8000
CMD ["sh", "-c", "python manage.py collectstatic --noinput && python manage.py migrate --noinput && exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 1 --access-logfile - --error-logfile -"]
