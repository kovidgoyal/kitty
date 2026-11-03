/*
 * functions.h
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

// The Vulkan functions used by the driver. libvulkan is loaded at runtime,
// so that kitty has no link time dependency on it, and these are loaded from
// it with vkGetInstanceProcAddr() and vkGetDeviceProcAddr().

#pragma once

#define VK_NO_PROTOTYPES
#define VK_USE_PLATFORM_XLIB_KHR
#define VK_USE_PLATFORM_WAYLAND_KHR
#include <vulkan/vulkan.h>

// Functions that need no instance
#define VK_GLOBAL_FUNCTIONS(X)                \
    X(vkCreateInstance)                       \
    X(vkEnumerateInstanceExtensionProperties) \
    X(vkEnumerateInstanceLayerProperties)     \
    X(vkEnumerateInstanceVersion)

#define VK_INSTANCE_FUNCTIONS(X)                 \
    X(vkDestroyInstance)                         \
    X(vkEnumeratePhysicalDevices)                \
    X(vkGetPhysicalDeviceProperties)             \
    X(vkGetPhysicalDeviceProperties2)            \
    X(vkGetPhysicalDeviceFeatures2)              \
    X(vkGetPhysicalDeviceQueueFamilyProperties)  \
    X(vkGetPhysicalDeviceMemoryProperties)       \
    X(vkGetPhysicalDeviceFormatProperties)       \
    X(vkEnumerateDeviceExtensionProperties)      \
    X(vkCreateDevice)                            \
    X(vkGetDeviceProcAddr)                       \
    X(vkDestroySurfaceKHR)                       \
    X(vkGetPhysicalDeviceSurfaceSupportKHR)      \
    X(vkGetPhysicalDeviceSurfaceCapabilitiesKHR) \
    X(vkGetPhysicalDeviceSurfaceFormatsKHR)      \
    X(vkGetPhysicalDeviceSurfacePresentModesKHR)

// Only the functions of the windowing system in use are loaded
#define VK_XLIB_FUNCTIONS(X)  \
    X(vkCreateXlibSurfaceKHR) \
    X(vkGetPhysicalDeviceXlibPresentationSupportKHR)

#define VK_WAYLAND_FUNCTIONS(X)  \
    X(vkCreateWaylandSurfaceKHR) \
    X(vkGetPhysicalDeviceWaylandPresentationSupportKHR)

// Loaded only if the debug utils extension is enabled
#define VK_DEBUG_FUNCTIONS(X)          \
    X(vkCreateDebugUtilsMessengerEXT)  \
    X(vkDestroyDebugUtilsMessengerEXT) \
    X(vkSetDebugUtilsObjectNameEXT)

#define VK_DEVICE_FUNCTIONS(X)       \
    X(vkDestroyDevice)               \
    X(vkGetDeviceQueue)              \
    X(vkDeviceWaitIdle)              \
    X(vkQueueWaitIdle)               \
    X(vkQueueSubmit2)                \
    X(vkQueuePresentKHR)             \
    X(vkCreateSwapchainKHR)          \
    X(vkDestroySwapchainKHR)         \
    X(vkGetSwapchainImagesKHR)       \
    X(vkAcquireNextImageKHR)         \
    X(vkCreateCommandPool)           \
    X(vkDestroyCommandPool)          \
    X(vkResetCommandPool)            \
    X(vkAllocateCommandBuffers)      \
    X(vkBeginCommandBuffer)          \
    X(vkEndCommandBuffer)            \
    X(vkCreateFence)                 \
    X(vkDestroyFence)                \
    X(vkWaitForFences)               \
    X(vkGetFenceStatus)              \
    X(vkResetFences)                 \
    X(vkCreateSemaphore)             \
    X(vkDestroySemaphore)            \
    X(vkAllocateMemory)              \
    X(vkFreeMemory)                  \
    X(vkMapMemory)                   \
    X(vkUnmapMemory)                 \
    X(vkCreateBuffer)                \
    X(vkDestroyBuffer)               \
    X(vkGetBufferMemoryRequirements) \
    X(vkBindBufferMemory)            \
    X(vkCreateImage)                 \
    X(vkDestroyImage)                \
    X(vkGetImageMemoryRequirements)  \
    X(vkBindImageMemory)             \
    X(vkCreateImageView)             \
    X(vkDestroyImageView)            \
    X(vkCreateSampler)               \
    X(vkDestroySampler)              \
    X(vkCreateShaderModule)          \
    X(vkDestroyShaderModule)         \
    X(vkCreateDescriptorSetLayout)   \
    X(vkDestroyDescriptorSetLayout)  \
    X(vkCreatePipelineLayout)        \
    X(vkDestroyPipelineLayout)       \
    X(vkCreateGraphicsPipelines)     \
    X(vkDestroyPipeline)             \
    X(vkCmdPipelineBarrier2)         \
    X(vkCmdBeginRendering)           \
    X(vkCmdEndRendering)             \
    X(vkCmdBindPipeline)             \
    X(vkCmdSetViewport)              \
    X(vkCmdSetScissor)               \
    X(vkCmdBindVertexBuffers2)       \
    X(vkCmdBindIndexBuffer)          \
    X(vkCmdDrawIndexed)              \
    X(vkCmdPushConstants)            \
    X(vkCmdPushDescriptorSetKHR)     \
    X(vkCmdCopyBufferToImage)        \
    X(vkCmdCopyImageToBuffer)        \
    X(vkCmdCopyImage)                \
    X(vkCmdBlitImage)                \
    X(vkCmdClearAttachments)

#define VK_DECLARE_FUNCTION(name) extern PFN_##name name;
VK_GLOBAL_FUNCTIONS(VK_DECLARE_FUNCTION)
VK_INSTANCE_FUNCTIONS(VK_DECLARE_FUNCTION)
VK_XLIB_FUNCTIONS(VK_DECLARE_FUNCTION)
VK_WAYLAND_FUNCTIONS(VK_DECLARE_FUNCTION)
VK_DEBUG_FUNCTIONS(VK_DECLARE_FUNCTION)
VK_DEVICE_FUNCTIONS(VK_DECLARE_FUNCTION)
extern PFN_vkGetInstanceProcAddr vkGetInstanceProcAddr;
