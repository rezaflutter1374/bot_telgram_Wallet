from __future__ import annotations


class AppError(Exception):
    __slots__ = ()


class NotFound(AppError):
    __slots__ = ()


class Forbidden(AppError):
    __slots__ = ()


class ValidationError(AppError):
    __slots__ = ()


class QuoteExpired(AppError):
    __slots__ = ()


class InsufficientDeposit(AppError):
    __slots__ = ()
