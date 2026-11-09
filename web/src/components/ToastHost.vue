<script setup lang="ts">
import { store } from '../store'
</script>

<template>
  <div class="toast" :class="{ show: !!store.toast }">{{ store.toast }}</div>
</template>
