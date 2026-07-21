import { identityRepository } from "../infrastructure/identity-repository";

export const identityService = identityRepository;
export type { RoleAssignment, UserDetail } from "../domain/models";
