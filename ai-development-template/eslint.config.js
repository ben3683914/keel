import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(...tseslint.configs.recommendedTypeChecked, {
  languageOptions: {
    globals: globals.node,
    parserOptions: {
      project: "./tsconfig.test.json",
      tsconfigRootDir: import.meta.dirname,
    },
  },
});
