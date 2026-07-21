import { afterEach, describe, expect, it, vi } from "vitest";
import { request, withQuery } from "./index";

afterEach(()=>vi.unstubAllGlobals());

describe("admin API transport",()=>{
  it("adds a correlation id and maps structured field errors",async()=>{
    const fetchMock=vi.fn(async(_input:RequestInfo|URL,init?:RequestInit)=>{
      expect(new Headers(init?.headers).get("X-Correlation-ID")).toBeTruthy();
      return new Response(JSON.stringify({detail:{code:"validation_failed",message:"配置无效",field_errors:[{field:"config.host",message:"必填"}]}}),{status:422,headers:{"content-type":"application/json","x-correlation-id":"corr-1"}});
    });
    vi.stubGlobal("fetch",fetchMock);
    await expect(request("/api/admin/tool-resources")).rejects.toEqual(expect.objectContaining({code:"validation_failed",correlationId:"corr-1",fieldErrors:[{field:"config.host",message:"必填"}]}));
  });

  it("builds bounded query strings without empty values",()=>{
    expect(withQuery("/api/admin/jobs",{status:"FAILED",limit:25,cursor:"",user_id:undefined})).toBe("/api/admin/jobs?status=FAILED&limit=25");
  });
});
