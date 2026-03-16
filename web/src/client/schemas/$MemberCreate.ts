/* generated using openapi-typescript-codegen -- do no edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export const $MemberCreate = {
  properties: {
    name: {
      type: "string",
      isRequired: true,
      pattern: "^[a-zA-Z0-9\u4e00-\u9fff][a-zA-Z0-9_\u4e00-\u9fff-]{0,63}$",
    },
    backstory: {
      type: "any-of",
      contains: [
        {
          type: "string",
        },
        {
          type: "null",
        },
      ],
    },
    role: {
      type: "string",
      isRequired: true,
    },
    type: {
      type: "string",
      isRequired: true,
    },
    owner_of: {
      type: "any-of",
      contains: [
        {
          type: "number",
        },
        {
          type: "null",
        },
      ],
    },
    position_x: {
      type: "number",
      isRequired: true,
    },
    position_y: {
      type: "number",
      isRequired: true,
    },
    source: {
      type: "any-of",
      contains: [
        {
          type: "number",
        },
        {
          type: "null",
        },
      ],
    },
    provider: {
      type: "string",
    },
    model: {
      type: "string",
    },
    temperature: {
      type: "number",
    },
    interrupt: {
      type: "boolean",
    },
  },
} as const;
