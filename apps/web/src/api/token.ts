/**
 * Токен доступа для запросов к API.
 *
 * Клиент API живёт вне дерева компонентов, и хук аутентификации ему
 * недоступен: провайдер кладёт сюда способ получить свежий токен, а клиент
 * спрашивает его перед каждым запросом. Спрашивать нужно каждый раз —
 * токен живёт минуты и молча обновляется в фоне.
 */
let read: () => string | undefined = () => undefined;

export function provideAccessToken(reader: () => string | undefined): void {
  read = reader;
}

export function accessToken(): string | undefined {
  return read();
}
