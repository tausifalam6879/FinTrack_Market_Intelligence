FROM maven:3.9.16-eclipse-temurin-21 AS build

WORKDIR /workspace
COPY pom.xml .
RUN mvn --batch-mode dependency:go-offline
COPY src ./src
RUN mvn --batch-mode package -DskipTests

FROM eclipse-temurin:21-jre-alpine

ENV PORT=8080 \
    FINTRACK_GATEWAY_UPSTREAM_BASE_URL=http://api:8000

RUN addgroup -S fintrack && adduser -S -G fintrack fintrack
WORKDIR /app
COPY --from=build --chown=fintrack:fintrack /workspace/target/market-gateway-*.jar /app/market-gateway.jar

USER fintrack
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD wget -q -O /dev/null "http://127.0.0.1:${PORT}/health/ready" || exit 1

ENTRYPOINT ["java", "-jar", "/app/market-gateway.jar"]
