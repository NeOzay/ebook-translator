import logging
from pathlib import Path


class LLMLogger(logging.Logger):
    """2-channel logger for LLM interactions.

    Channel 1 — parent logger (console + translation.log):
        Receives WARNING and above.

    Channel 2 — per-exchange file:
        Receives all levels. Activated via set_exchange_file().

    Args:
        parent_logger: Configured module-level logger for channel 1.
        model: LLM model name (informational).
    """

    def __init__(self, parent_logger: logging.Logger) -> None:
        super().__init__(name=parent_logger.name, level=logging.DEBUG)
        self._parent_logger = parent_logger
        self._exchange_handler: logging.FileHandler | None = None
        self.propagate = False

    def set_exchange_file(self, path: Path | None) -> None:
        """Point channel 2 at a file, or disable it.

        Le répertoire parent est créé si nécessaire : le répertoire de session
        n'existe sur disque qu'une fois qu'un `LazyFileHandler` a émis, ce qui
        n'est pas garanti avant le premier échange LLM.

        Args:
            path: Target file for LLM trace output. None closes the channel.
        """
        if self._exchange_handler is not None:
            self._exchange_handler.close()
            self._exchange_handler = None
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            handler = logging.FileHandler(path, mode="a", encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(message)s"))
            self._exchange_handler = handler

    def callHandlers(self, record: logging.LogRecord) -> None:
        if record.levelno >= logging.WARNING:
            self._parent_logger.handle(record)
        if self._exchange_handler is not None:
            self._exchange_handler.emit(record)
