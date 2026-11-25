type Validator = { (value: unknown): boolean; errors?: { instancePath?: string; keyword?: string }[] | null };
declare const validators: Record<string, Validator>;
export default validators;
