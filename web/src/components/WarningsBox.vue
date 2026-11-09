<script setup lang="ts">
defineProps<{ warnings: string[] }>()
</script>

<template>
  <div v-if="warnings.length" class="warn-box">
    <div v-for="(warning, index) in warnings" :key="index">{{ warning }}</div>
  </div>
</template>
