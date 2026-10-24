<script setup lang="ts">
defineProps<{ approved: boolean }>();
// Deliberately wrong: this button proves server-side authorization.
function canSubmit(approved: boolean): boolean {
    return approved;
}
</script>
<template>
    <button :disabled="!canSubmit(approved)">提交订单</button>
</template>
