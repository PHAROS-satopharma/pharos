/**
 * The password rule, kept equal to supabase/config.toml [auth]: minimum_password_length = 12 and
 * password_requirements = "lower_upper_letters_digits". The server refuses anything weaker, so the
 * form says so first, in plain words.
 */
export const PASSWORD_MIN_LENGTH = 12;

export const PASSWORD_HINT = `At least ${PASSWORD_MIN_LENGTH} characters, with a lower-case letter, a capital letter and a digit.`;

/** What is wrong with a new password, or `null` when the server will accept it. */
export function passwordProblem(pw: string): string | null {
  if (pw.length < PASSWORD_MIN_LENGTH) return `Use at least ${PASSWORD_MIN_LENGTH} characters.`;
  if (!/[a-z]/.test(pw) || !/[A-Z]/.test(pw) || !/[0-9]/.test(pw)) {
    return 'Use at least one lower-case letter, one capital letter and one digit.';
  }
  return null;
}
