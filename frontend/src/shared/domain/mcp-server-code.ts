import { z } from "zod"

export const mcpServerCodeSchema = z
  .string()
  .min(1)
  .max(120)
  .regex(/^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$/)

export type McpServerCode = z.infer<typeof mcpServerCodeSchema>
