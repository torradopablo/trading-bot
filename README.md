# 🤖 Binance Futures Trading Bot - EMA/RSI/ATR Strategy

Este es un bot de trading automático para **Binance Futures** (BTCUSDT por defecto) que utiliza una combinación de medias móviles exponenciales (EMA), el índice de fuerza relativa (RSI) y el rango verdadero promedio (ATR) para la gestión de riesgo.

## 📊 Estrategia de Trading

El bot opera bajo una estrategia tendencial con filtros de momentum y gestión de riesgo dinámica:

1.  **Cruce de EMAs (9/21)**: Determina la dirección de la tendencia. 
    *   **LONG**: Cuando la EMA 9 cruza hacia arriba la EMA 21.
    *   **SHORT**: Cuando la EMA 9 cruza hacia abajo la EMA 21.
2.  **Filtro RSI (14)**: Evita entrar en posiciones cuando el mercado está en niveles extremos.
    *   Para **LONG**: El RSI debe ser menor a 70 (no sobrecomprado).
    *   Para **SHORT**: El RSI debe ser mayor a 30 (no sobrevendido).
3.  **Gestión de Riesgo (ATR)**:
    *   **Stop Loss (SL)**: Se sitúa a 1.5 * ATR del precio de entrada.
    *   **Take Profit (TP)**: Se sitúa a 3.0 * ATR del precio de entrada (Ratio Riesgo/Beneficio 1:2).
    *   **Riesgo por trade**: Calcula automáticamente el tamaño de la posición para arriesgar solo el 2% del balance disponible.
    *   **Apalancamiento**: Configurado por defecto en 3x.

## 🚀 Requisitos Previos

*   Cuenta en Binance con Futuros habilitados.
*   API Key y API Secret de Binance (preferiblemente de Testnet para pruebas iniciales).
*   Bot de Telegram (opcional, para notificaciones).
*   Docker y Docker Compose instalados (recomendado).

## 🛠️ Configuración

1.  Clona este repositorio o copia los archivos.
2.  Crea un archivo `.env` basado en el `env.example`:
    ```bash
    cp env.example .env
    ```
3.  Completa tus credenciales en el archivo `.env`:
    *   `BINANCE_API_KEY`: Tu clave API.
    *   `BINANCE_API_SECRET`: Tu clave secreta.
    *   `TELEGRAM_BOT_TOKEN`: El token proporcionado por [@BotFather](https://t.me/BotFather).
    *   `TELEGRAM_CHAT_ID`: Tu ID de chat (puedes obtenerlo de [@userinfobot](https://t.me/userinfobot)).

## 🐳 Ejecución con Docker (Recomendado)

El bot está preparado para correr en un contenedor Docker de forma ininterrumpida.

```bash
docker-compose up -d --build
```

Esto levantará el bot en segundo plano y guardará los logs en la carpeta `./logs`.

## 🐍 Ejecución Local (Python)

Si prefieres correrlo directamente con Python:

1.  Instala las dependencias:
    ```bash
    pip install -r requirements.txt
    ```
2.  Ejecuta el bot:
    ```bash
    python binance_bot.py
    ```

## ⚙️ Parámetros del Bot

Puedes ajustar el comportamiento del bot modificando el diccionario `CONFIG` en `binance_bot.py`:

*   `symbol`: Par a tradear (Ej: "BTCUSDT").
*   `interval`: Temporalidad de las velas (Ej: "15m").
*   `leverage`: Apalancamiento (Ej: 3).
*   `risk_pct`: Porcentaje de balance a arriesgar por trade (Ej: 0.02 para 2%).
*   `testnet`: `True` para usar Binance Testnet, `False` para dinero real.

## 📱 Notificaciones de Telegram

El bot envía mensajes automáticos cuando:
*   Se inicia el script.
*   Se abre una nueva orden (con detalles de SL, TP y Riesgo).
*   Se cierra una posición (con el PnL obtenido).
*   Ocurre un error.
*   Resumen horario (Heartbeat) con el estado actual del mercado y la cuenta.

---

### ⚠️ Descargo de Responsabilidad
Este software es solo para fines educativos. El trading de futuros implica un riesgo significativo de pérdida. Los autores no se hacen responsables de las pérdidas financieras incurridas por el uso de este bot. **Prueba siempre en Testnet antes de usar dinero real.**
