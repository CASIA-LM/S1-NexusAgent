/* generated using openapi-typescript-codegen -- do no edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export const $TeamUpdate = {
  properties: {
    name: {
      type: "any-of",
      contains: [
        {
          type: "string",
          pattern: "^[a-zA-Z0-9\u4e00-\u9fff][a-zA-Z0-9_\u4e00-\u9fff-]{0,63}$",
        },
        {
          type: "null",
        },
      ],
    },
    description: {
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
    icon: {
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
  },
} as const;
