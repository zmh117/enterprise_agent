import { useQuery } from "@tanstack/react-query";
import { operationsRepository } from "../infrastructure/admin-operations-repository";

import type { OperationsFilters } from "../domain/models";

export const useDashboard = (filters:OperationsFilters={}) => useQuery({ queryKey: ["admin", "dashboard",filters], queryFn: ()=>operationsRepository.dashboard(filters), refetchInterval: 30_000 });
export const useQueues = () => useQuery({ queryKey: ["admin", "queues"], queryFn: operationsRepository.queues, refetchInterval: 15_000 });
export const useJobs = (filters:OperationsFilters={}) => useQuery({ queryKey: ["admin", "jobs",filters], queryFn: ()=>operationsRepository.jobs(filters) });
export const useJob = (id:string) => useQuery({ queryKey:["admin","job",id], queryFn:()=>operationsRepository.job(id), enabled:Boolean(id) });
export const useConversations = (filters:OperationsFilters={}) => useQuery({ queryKey: ["admin", "conversations",filters], queryFn: ()=>operationsRepository.conversations(filters) });
export const useConversation = (id:string) => useQuery({queryKey:["admin","conversation",id],queryFn:()=>operationsRepository.conversation(id),enabled:Boolean(id)});
export const useAttachments = (filters:OperationsFilters={}) => useQuery({ queryKey: ["admin", "attachments",filters], queryFn: ()=>operationsRepository.attachments(filters) });
export const useAttachment = (id:string) => useQuery({queryKey:["admin","attachment",id],queryFn:()=>operationsRepository.attachment(id),enabled:Boolean(id)});
