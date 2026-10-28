import { ApiError } from "./client";
import { shouldRetry } from "./queries";

describe("política de retry das consultas", () => {
  it.each([400, 401, 404, 409, 413, 422, 429])("%i não é repetido (não muda com retry)", (status) => {
    expect(shouldRetry(0, new ApiError(status, "x"))).toBe(false);
  });
  it.each([0, 500, 502, 503, 504])("%i é repetido até 2 vezes", (status) => {
    const e = new ApiError(status, "x");
    expect(shouldRetry(0, e)).toBe(true);
    expect(shouldRetry(1, e)).toBe(true);
    expect(shouldRetry(2, e)).toBe(false);
  });
});
