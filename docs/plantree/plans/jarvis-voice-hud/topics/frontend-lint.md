# 主题:hud-app 前端 lint 约定(Phase 1 启用)

决定(用户,2026-06-11):**ESLint 推迟到 Phase 1 搭 `hud-app/` TS 工程时一起做**,用项目同款
**flat config(`eslint.config.mjs`)**,不用旧版 `.eslintrc.json`。Phase 0 不动。

参考项目现有:`ui-tui/eslint.config.mjs` 已是 flat config —— 新前端沿用同风格。

## 约定的规则(用户提供,已修正符号 + 转 flat config 待用)
等价于用户那份 `.eslintrc` 的 flat-config 形态,放进 `hud-app/eslint.config.mjs`:

```js
import js from "@eslint/js";
import tseslint from "typescript-eslint";

export default tseslint.config(
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    languageOptions: {
      // browser + node 全局;es2021+
      globals: { /* browser + node globals, e.g. via globals pkg */ },
    },
    rules: {
      "@typescript-eslint/no-explicit-any": "warn",
      quotes: ["warn", "double"],
      indent: ["warn", 2],
      "no-console": "off",
      // 下面几条按需在 Phase 1 打开:
      // "max-lines": ["warn", { max: 300, skipBlankLines: true, skipComments: true }],
      // "max-lines-per-function": ["warn", { max: 50, skipBlankLines: true, skipComments: true }],
      // "complexity": ["warn", 10],
      // "semi": ["warn", "always"],
    },
  },
);
```

需要的 devDeps(Phase 1 搭工程时装):`eslint`、`typescript-eslint`、`@eslint/js`、`globals`。

## 注意
- 用户原始粘贴里符号(逗号/冒号/连字符)被吞了,且 `max`/`indent` 缺数值 —— 上面已按常见默认补全
  (`indent: 2`、`max-lines: 300`、`max-lines-per-function: 50`、`complexity: 10`),Phase 1 落地时与用户再确认这些数值。
